import random
import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from app.database import get_database, clean_doc, clean_docs
from app.models.schemas import (
    OrderOut,
    OrderCreate,
    OrderStatusUpdate,
    RazorpayOrderCreateRequest,
    RazorpayPaymentVerifyRequest,
    RazorpayPaymentFailedRequest
)
from app.security import get_current_admin
from app.razorpay_service import (
    create_razorpay_order,
    verify_razorpay_signature,
    fetch_payment_details,
    get_razorpay_status,
    is_razorpay_configured
)

router = APIRouter(prefix="/api/orders", tags=["Orders"])

async def calculate_trusted_order_total(db, items: list, coupon_code: Optional[str] = None):
    """
    Calculate subtotal, discount, shipping, and total from trusted MongoDB product prices.
    Returns (trusted_total, subtotal, discount, verified_items_list).
    """
    subtotal = 0.0
    verified_items = []

    for it in items:
        item_dict = it.model_dump() if hasattr(it, "model_dump") else dict(it)
        pid = item_dict.get("id")
        qty = max(1, int(item_dict.get("qty", 1)))

        # Lookup true price from MongoDB products collection
        product = None
        if pid is not None:
            try:
                numeric_id = int(pid)
                product = await db.products.find_one({"id": numeric_id})
            except (ValueError, TypeError):
                product = await db.products.find_one({"id": str(pid)})

        if product and "price" in product:
            trusted_price = float(product["price"])
            item_name = product.get("name", item_dict.get("name", "Jewellery Item"))
            item_img = product.get("img", item_dict.get("img", ""))
        else:
            trusted_price = max(0.0, float(item_dict.get("price", 0.0)))
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

    # Shipping fee calculation (Free above freeShippingThreshold, default 2500)
    settings_doc = await db.settings.find_one({"key": "main"})
    settings_data = settings_doc.get("data", {}) if settings_doc else {}
    free_threshold = float(settings_data.get("freeShippingThreshold", 2500))
    shipping_fee = 0.0 if (subtotal - discount) >= free_threshold else 150.0

    total = max(0.0, round(subtotal - discount + shipping_fee, 2))
    return total, subtotal, discount, verified_items

# ========================================================
# Razorpay Integration Endpoints (Declared before /{order_id})
# ========================================================

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
    trusted_total, subtotal, discount, verified_items = await calculate_trusted_order_total(
        db=db,
        items=payload.items,
        coupon_code=payload.coupon_code
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
        "status": "Payment Pending",
        "paymentMethod": "Razorpay Online",
        "paymentStatus": "Pending",
        "address": payload.address or "",
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
        "customer": {
            "name": payload.customer,
            "email": payload.email,
            "contact": payload.phone
        }
    }

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

    # 3. Prevent duplicate payment confirmation
    if order.get("paymentStatus") == "Paid":
        return {
            "success": True,
            "message": "Payment already verified and confirmed.",
            "order": clean_doc(order)
        }

    # 4. Fetch verified payment details from Razorpay API
    pay_details = fetch_payment_details(payload.razorpay_payment_id)
    payment_method_label = "Razorpay Online"
    if pay_details and pay_details.get("method"):
        payment_method_label = f"Razorpay ({pay_details['method'].upper()})"

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
    return {
        "success": True,
        "message": "Payment verified and order confirmed successfully.",
        "order": clean_doc(updated_order)
    }

@router.post("/razorpay/payment-failed")
async def record_payment_failure_endpoint(payload: RazorpayPaymentFailedRequest):
    """
    Record payment failure or cancellation without incorrectly marking order as paid.
    """
    db = get_database()
    order = await db.orders.find_one({"id": payload.order_id})
    if not order and payload.razorpay_order_id:
        order = await db.orders.find_one({"razorpay_order_id": payload.razorpay_order_id})

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if order and order.get("paymentStatus") != "Paid":
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

# ========================================================
# Standard Orders CRUD Endpoints
# ========================================================

@router.get("", response_model=List[OrderOut])
async def get_orders(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
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
async def get_order_by_id(order_id: str):
    db = get_database()
    order = await db.orders.find_one({"id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    return clean_doc(order)

@router.post("", response_model=OrderOut, status_code=201)
async def create_order(payload: OrderCreate):
    """Standard order creation (Cash on Delivery or direct record)."""
    db = get_database()
    now = datetime.datetime.now()
    now_iso = now.isoformat()
    formatted_date = payload.date or now.strftime("%d %b %Y")

    order_id = payload.id
    if not order_id:
        while True:
            rand_num = random.randint(100, 9999)
            order_id = f"DBD-{now.year}-{rand_num}"
            if not await db.orders.find_one({"id": order_id}):
                break

    items_dict_list = [item.model_dump() for item in payload.items]

    # If COD, default payment status is Pending
    pay_status = payload.paymentStatus or ("Paid" if "online" in (payload.paymentMethod or "").lower() else "Pending")

    doc = {
        "id": order_id,
        "customer": payload.customer,
        "email": payload.email,
        "phone": payload.phone or "",
        "date": formatted_date,
        "total": float(payload.total),
        "status": payload.status or "Processing",
        "paymentMethod": payload.paymentMethod or "Cash on Delivery",
        "paymentStatus": pay_status,
        "address": payload.address or "",
        "items": items_dict_list,
        "razorpay_order_id": payload.razorpay_order_id,
        "razorpay_payment_id": payload.razorpay_payment_id,
        "currency": payload.currency or "INR",
        "notes": payload.notes,
        "created_at": now_iso,
        "updated_at": now_iso
    }
    await db.orders.insert_one(doc)
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
