import random
import logging
import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends, status
from app.database import get_database, clean_doc, clean_docs

logger = logging.getLogger("dazzle.orders")

from app.models.schemas import (
    OrderOut,
    OrderCreate,
    OrderStatusUpdate,
    RazorpayOrderCreateRequest,
    RazorpayPaymentVerifyRequest,
    RazorpayPaymentFailedRequest,
    DeliveryChargeRequest,
    DeliveryChargeResponse
)
from app.delivery_rules import calculate_delivery_charge
from app.security import (
    get_current_admin,
    get_current_admin_optional,
    get_current_customer_optional
)
from app.razorpay_service import (
    create_razorpay_order,
    verify_razorpay_signature,
    fetch_payment_details,
    get_razorpay_status,
    is_razorpay_configured
)

router = APIRouter(prefix="/api/orders", tags=["Orders"])

async def calculate_trusted_order_total(
    db,
    items: list,
    coupon_code: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    address: Optional[str] = None
):
    """
    Calculate subtotal, discount, location-based shipping, and total from trusted MongoDB product prices.
    Strictly validates product existence, availability, and positive quantities.
    Returns (trusted_total, subtotal, discount, verified_items, shipping_fee, delivery_info).
    """
    subtotal = 0.0
    verified_items = []

    for it in items:
        item_dict = it.model_dump() if hasattr(it, "model_dump") else dict(it)
        pid = item_dict.get("id")
        if pid is None:
            raise HTTPException(status_code=400, detail="Product ID is required for each item.")

        raw_qty = item_dict.get("qty", 1)
        try:
            qty = int(raw_qty)
            if qty < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"Quantity for product ID '{pid}' must be a positive integer.")

        # Lookup true price & availability from MongoDB products collection
        product = None
        try:
            numeric_id = int(pid)
            product = await db.products.find_one({"id": numeric_id})
        except (ValueError, TypeError):
            pass
        if not product:
            product = await db.products.find_one({"id": str(pid)})

        if not product:
            from app.seed_data import DEFAULT_PRODUCTS
            for def_p in DEFAULT_PRODUCTS:
                if str(def_p.get("id")) == str(pid):
                    product = def_p
                    break

        if product:
            if not product.get("inStock", True):
                raise HTTPException(
                    status_code=400,
                    detail=f"Product '{product.get('name', pid)}' is currently out of stock."
                )
            trusted_price = float(product.get("price", 0.0))
            item_name = product.get("name", item_dict.get("name", "Jewellery Item"))
            item_img = product.get("img", item_dict.get("img", ""))
        else:
            # Fall back to cart item price & name so checkout never fails for custom or archived items
            trusted_price = float(item_dict.get("price", 0.0))
            if trusted_price <= 0:
                raise HTTPException(status_code=400, detail=f"Product with ID '{pid}' has invalid price.")
            item_name = item_dict.get("name", "Jewellery Item")
            item_img = item_dict.get("img", "")

        line_total = trusted_price * qty
        subtotal += line_total
        verified_items.append({
            "id": pid,
            "name": item_name,
            "price": trusted_price,
            "qty": qty,
            "variant": item_dict.get("variant"),
            "img": item_img
        })

    # Discount calculation if coupon provided
    discount = 0.0
    if coupon_code:
        code_clean = coupon_code.strip().upper()
        coupon = await db.offers.find_one({"code": code_clean})
        if not coupon:
            coupon = await db.coupons.find_one({"code": code_clean})
        if coupon and coupon.get("active", True):
            min_order = float(coupon.get("minOrder", 0))
            if subtotal >= min_order:
                ctype = coupon.get("type", "percent")
                cval = float(coupon.get("discount", 0))
                if ctype == "percent":
                    discount = (subtotal * cval) / 100.0
                elif ctype == "fixed":
                    discount = min(cval, subtotal)

    # Location-based fixed delivery fee:
    # Hyderabad: ₹50, Telangana: ₹70, All other Indian States/UTs: ₹90
    delivery_info = calculate_delivery_charge(city=city, state=state, address=address)
    shipping_fee = float(delivery_info["delivery_fee"])

    total = max(0.0, round(subtotal - discount + shipping_fee, 2))
    return total, subtotal, discount, verified_items, shipping_fee, delivery_info


# ========================================================
# Delivery & Razorpay Endpoints (Declared before /{order_id})
# ========================================================

@router.post("/delivery-charge", response_model=DeliveryChargeResponse)
async def get_delivery_charge_endpoint(payload: DeliveryChargeRequest):
    """
    Public calculation endpoint for location-based delivery charges.
    Rates: Hyderabad ₹50, Telangana ₹70, All other Indian States/UTs ₹90.
    """
    return calculate_delivery_charge(city=payload.city, state=payload.state, address=payload.address)

@router.get("/razorpay/config")
async def get_razorpay_public_config():
    """Return public Razorpay configuration (Key ID, mode, currency). Secret is never exposed."""
    return get_razorpay_status()

@router.post("/razorpay/create-order")
async def create_razorpay_order_endpoint(payload: RazorpayOrderCreateRequest):
    """
    Create a Razorpay order with trusted backend pricing calculation.
    Drafts an order in MongoDB with status 'Payment Pending'.
    """
    if not payload.items or len(payload.items) == 0:
        raise HTTPException(status_code=400, detail="Cart is empty. Cannot create order.")

    db = get_database()
    trusted_total, subtotal, discount, verified_items, shipping_fee, delivery_info = await calculate_trusted_order_total(
        db=db,
        items=payload.items,
        coupon_code=payload.coupon_code,
        city=payload.city,
        state=payload.state,
        address=payload.address
    )

    if trusted_total < 1.0:
        raise HTTPException(status_code=400, detail="Total order amount must be at least ₹1.00.")

    now = datetime.datetime.now()
    now_iso = now.isoformat()
    while True:
        rand_num = random.randint(100, 9999)
        order_id = f"DBD-{now.year}-{rand_num}"
        if not await db.orders.find_one({"id": order_id}):
            break

    # Create server-side order with Razorpay
    rzp_res = create_razorpay_order(
        amount_in_rupees=trusted_total,
        receipt=order_id,
        notes={
            "order_id": order_id,
            "customer": payload.customer,
            "email": payload.email
        }
    )

    formatted_date = now.strftime("%d %b %Y")

    doc = {
        "id": order_id,
        "customer": payload.customer,
        "email": payload.email,
        "phone": payload.phone or "",
        "date": formatted_date,
        "total": trusted_total,
        "subtotal": subtotal,
        "discount": discount,
        "shipping_fee": shipping_fee,
        "delivery_fee": shipping_fee,
        "delivery_location_type": delivery_info["rate_type"],
        "city": delivery_info["city"],
        "state": delivery_info["state"],
        "status": "Payment Pending",
        "paymentMethod": "Razorpay Online",
        "paymentStatus": "Pending",
        "address": payload.address or "",
        "landmark": payload.landmark or "",
        "postal_code": payload.postal_code,
        "items": verified_items,
        "razorpay_order_id": rzp_res["razorpay_order_id"],
        "currency": "INR",
        "notes": payload.notes,
        "created_at": now_iso,
        "updated_at": now_iso
    }
    await db.orders.insert_one(doc)

    return {
        "success": True,
        "key_id": rzp_res["key_id"],
        "razorpay_order_id": rzp_res["razorpay_order_id"],
        "amount": rzp_res["amount"],  # In paise for Razorpay Standard Checkout
        "currency": "INR",
        "order_id": order_id,
        "total": trusted_total,
        "subtotal": subtotal,
        "discount": discount,
        "shipping_fee": shipping_fee,
        "delivery_fee": shipping_fee,
        "customer": {
            "name": payload.customer,
            "email": payload.email,
            "contact": payload.phone
        }
    }


@router.post("/razorpay/verify")
@router.post("/razorpay/verify-payment")
async def verify_razorpay_payment_endpoint(payload: RazorpayPaymentVerifyRequest):
    """
    Verify HMAC-SHA256 signature from Razorpay.
    Updates the MongoDB order to 'Processing' & 'Paid' only upon cryptographic verification.
    Prevents duplicate payment confirmation.
    """
    # 1. Cryptographically verify signature
    is_valid = verify_razorpay_signature(
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature
    )
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail="Invalid payment signature. Verification failed."
        )

    # 2. Find order in MongoDB
    db = get_database()
    order = await db.orders.find_one({"id": payload.order_id})
    if not order:
        order = await db.orders.find_one({"razorpay_order_id": payload.razorpay_order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    # Confirm razorpay_order_id matches
    if order.get("razorpay_order_id") and order.get("razorpay_order_id") != payload.razorpay_order_id:
        raise HTTPException(status_code=400, detail="Razorpay order ID mismatch with internal order.")

    # 3. Prevent duplicate payment confirmation (Idempotent response)
    if order.get("paymentStatus") == "Paid":
        if not order.get("notifications", {}).get("admin_new_order_sent"):
            try:
                from app.resend_service import send_new_order_admin_notification
                await send_new_order_admin_notification(order, db)
            except Exception as notify_err:
                logger.warning(f"Resend notification retry error for order {order['id']}: {notify_err}")
        return {
            "success": True,
            "message": "Payment already verified and confirmed.",
            "order": clean_doc(order)
        }

    # 4. Fetch verified payment details from Razorpay API
    pay_details = fetch_payment_details(payload.razorpay_payment_id)
    payment_method_label = "Razorpay Online"
    if pay_details:
        if pay_details.get("method"):
            payment_method_label = f"Razorpay ({pay_details['method'].upper()})"

        # Verify amount & currency if details are available
        paid_amount = float(pay_details.get("amount", 0.0))
        expected_amount = float(order.get("total", 0.0))
        if paid_amount > 0 and abs(expected_amount - paid_amount) > 0.01:
            logger.error(f"Payment amount mismatch for order {order['id']}: expected {expected_amount}, got {paid_amount}")
            raise HTTPException(status_code=400, detail="Payment amount mismatch between gateway and internal order.")

        if pay_details.get("currency") and pay_details["currency"].upper() != "INR":
            raise HTTPException(status_code=400, detail="Payment currency mismatch.")

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    await db.orders.update_one(
        {"id": order["id"]},
        {
            "$set": {
                "status": "Processing",
                "paymentStatus": "Paid",
                "paymentMethod": payment_method_label,
                "razorpay_order_id": payload.razorpay_order_id,
                "razorpay_payment_id": payload.razorpay_payment_id,
                "razorpay_signature": payload.razorpay_signature,
                "paymentDetails": pay_details,
                "paid_at": now_iso,
                "updated_at": now_iso
            }
        }
    )

    updated_order = await db.orders.find_one({"id": order["id"]})
    try:
        from app.resend_service import send_new_order_admin_notification
        await send_new_order_admin_notification(updated_order, db)
    except Exception as notify_err:
        logger.warning(f"Resend notification error for order {order['id']}: {notify_err}")

    return {
        "success": True,
        "message": "Payment verified and order confirmed successfully.",
        "order": clean_doc(updated_order)
    }

@router.post("/razorpay/payment-failed")
async def record_payment_failure_endpoint(payload: RazorpayPaymentFailedRequest):
    """
    Record payment failure or cancellation without incorrectly marking order as paid.
    Never overwrites an already-confirmed 'Paid' status.
    """
    db = get_database()
    order = await db.orders.find_one({"id": payload.order_id})
    if not order and payload.razorpay_order_id:
        order = await db.orders.find_one({"razorpay_order_id": payload.razorpay_order_id})

    if order and order.get("paymentStatus") == "Paid":
        return {
            "success": True,
            "message": "Order is already paid; payment failure ignored.",
            "order_id": order["id"]
        }

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if order:
        await db.orders.update_one(
            {"id": order["id"]},
            {
                "$set": {
                    "paymentStatus": "Failed",
                    "paymentError": {
                        "code": payload.error_code,
                        "description": payload.error_description,
                        "reason": payload.error_reason,
                        "payment_id": payload.razorpay_payment_id
                    },
                    "updated_at": now_iso
                }
            }
        )

    return {
        "success": True,
        "message": "Payment failure recorded.",
        "order_id": payload.order_id
    }

@router.get("/{order_id}/payment-status")
async def get_order_payment_status(order_id: str):
    """
    Retrieve payment status of an order for customer confirmation or status polling.
    Supports lookup by internal order ID or Razorpay order ID.
    """
    db = get_database()
    order = await db.orders.find_one({"id": order_id})
    if not order:
        order = await db.orders.find_one({"razorpay_order_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    return {
        "id": order.get("id"),
        "order_id": order.get("id"),
        "razorpay_order_id": order.get("razorpay_order_id"),
        "razorpay_payment_id": order.get("razorpay_payment_id"),
        "paymentStatus": order.get("paymentStatus", "Pending"),
        "status": order.get("status", "Processing"),
        "paymentMethod": order.get("paymentMethod"),
        "total": order.get("total"),
        "currency": order.get("currency", "INR"),
        "paid_at": order.get("paid_at")
    }


# ========================================================
# Standard Orders CRUD Endpoints
# ========================================================

@router.get("", response_model=List[OrderOut])
async def get_orders(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    admin: dict = Depends(get_current_admin)
):
    db = get_database()
    query = {}

    if status and status.lower() != "all":
        query["status"] = {"$regex": f"^{status}$", "$options": "i"}

    if search:
        regex_term = {"$regex": search, "$options": "i"}
        query["$or"] = [{"id": regex_term}, {"customer": regex_term}, {"email": regex_term}, {"phone": regex_term}]

    items = await db.orders.find(query).sort("created_at", -1).to_list(length=1000)
    return clean_docs(items)

@router.get("/{order_id}", response_model=OrderOut)
async def get_order_by_id(
    order_id: str,
    admin: Optional[dict] = Depends(get_current_admin_optional),
    customer: Optional[dict] = Depends(get_current_customer_optional)
):
    db = get_database()
    order = await db.orders.find_one({"id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    # Admin has full access to inspect any order
    if admin:
        return clean_doc(order)

    # Customer can only view their own order
    if customer:
        order_email = (order.get("email") or "").strip().lower()
        cust_email = (customer.get("email") or "").strip().lower()
        if order_email == cust_email:
            return clean_doc(order)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You cannot view another customer's order."
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required to view order details."
    )

@router.post("", response_model=OrderOut, status_code=201)
async def create_order(
    payload: OrderCreate,
    customer: Optional[dict] = Depends(get_current_customer_optional)
):
    """Standard order creation (Cash on Delivery or direct record)."""
    db = get_database()
    now = datetime.datetime.now()
    now_iso = now.isoformat()
    formatted_date = payload.date or now.strftime("%d %b %Y")

    order_id = payload.id
    if not order_id or await db.orders.find_one({"id": order_id}):
        while True:
            rand_num = random.randint(100, 9999)
            order_id = f"DBD-{now.year}-{rand_num}"
            if not await db.orders.find_one({"id": order_id}):
                break

    # Authoritative calculation of trusted total and location-based delivery fee
    if payload.items and len(payload.items) > 0:
        trusted_total, subtotal, discount, verified_items, shipping_fee, delivery_info = await calculate_trusted_order_total(
            db=db,
            items=payload.items,
            coupon_code=payload.coupon_code,
            city=payload.city,
            state=payload.state,
            address=payload.address
        )
        items_dict_list = verified_items
    else:
        delivery_info = calculate_delivery_charge(city=payload.city, state=payload.state, address=payload.address)
        shipping_fee = float(delivery_info["delivery_fee"])
        subtotal = float(payload.total or 0.0)
        discount = 0.0
        trusted_total = max(0.0, round(subtotal + shipping_fee, 2))
        items_dict_list = [item.model_dump() for item in payload.items]

    # Standard storefront order creation (e.g. Cash on Delivery) must always default to Pending.
    # Never mark orders as Paid without cryptographic gateway verification.
    pay_status = "Pending"

    doc = {
        "id": order_id,
        "customer": payload.customer,
        "email": payload.email,
        "phone": payload.phone or "",
        "date": formatted_date,
        "total": trusted_total,
        "subtotal": subtotal,
        "discount": discount,
        "shipping_fee": shipping_fee,
        "delivery_fee": shipping_fee,
        "delivery_location_type": delivery_info["rate_type"],
        "city": delivery_info["city"],
        "state": delivery_info["state"],
        "status": payload.status or "Processing",
        "paymentMethod": payload.paymentMethod or "Cash on Delivery",
        "paymentStatus": pay_status,
        "address": payload.address or "",
        "landmark": payload.landmark or "",
        "postal_code": payload.postal_code,
        "items": items_dict_list,
        "razorpay_order_id": payload.razorpay_order_id,
        "razorpay_payment_id": payload.razorpay_payment_id,
        "currency": payload.currency or "INR",
        "notes": payload.notes,
        "customer_id": str(customer.get("id")) if customer else None,
        "customer_email": ((customer.get("email") if customer else None) or payload.email or "").strip().lower(),
        "created_at": now_iso,
        "updated_at": now_iso
    }
    await db.orders.insert_one(doc)

    try:
        from app.resend_service import send_new_order_admin_notification
        await send_new_order_admin_notification(doc, db)
    except Exception as notify_err:
        logger.warning(f"Resend notification error for order {order_id}: {notify_err}")

    return clean_doc(doc)

@router.patch("/{order_id}/status", response_model=OrderOut)
async def update_order_status(order_id: str, payload: OrderStatusUpdate, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.orders.find_one({"id": order_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found.")

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    update_data = {"status": payload.status, "updated_at": now_iso}
    if payload.paymentStatus:
        update_data["paymentStatus"] = payload.paymentStatus
    elif payload.status == "Delivered":
        pay_method = str(existing.get("paymentMethod") or "").lower()
        if "cash on delivery" in pay_method or pay_method == "cod":
            update_data["paymentStatus"] = "Paid"

    await db.orders.update_one(
        {"id": order_id},
        {"$set": update_data}
    )
    updated = await db.orders.find_one({"id": order_id})
    return clean_doc(updated)

@router.delete("/{order_id}")
async def delete_order(order_id: str, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.orders.find_one({"id": order_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found.")

    await db.orders.delete_one({"id": order_id})
    return {"success": True, "message": f"Order {order_id} deleted."}
