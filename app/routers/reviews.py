import re
import datetime
from typing import List, Optional, Any, Union
from fastapi import APIRouter, HTTPException, Query, Depends, status
from app.database import get_database, clean_doc, clean_docs
from app.models.schemas import (
    ReviewOut,
    ReviewCreate,
    ReviewUpdate,
    ReviewStatusUpdate,
    ReviewEligibilityResponse
)
from app.security import (
    get_current_admin,
    get_current_admin_optional,
    get_current_customer_optional
)

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])


async def check_customer_review_eligibility(
    db,
    customer: dict,
    product_identifier: Any,
    order_id: Optional[str] = None
):
    """
    Authoritative backend eligibility verification.
    1. Validates that the product exists.
    2. Enforces one review per customer per product (checks pending & approved reviews).
    3. Searches customer's order records:
       - Disqualifies cancelled orders.
       - Qualifies delivered/completed orders, paid orders, or completed Cash on Delivery orders.
       - Verifies the product is in the order items.
    Returns: (eligible: bool, reason: str, message: str, product: Optional[dict], existing_review: Optional[dict])
    """
    import urllib.parse

    # 1. Locate Product
    prod = None
    target_str = str(product_identifier).strip() if product_identifier is not None else ""
    if target_str:
        target_str = urllib.parse.unquote(target_str).strip()

    if isinstance(product_identifier, int) or (isinstance(product_identifier, str) and product_identifier.isdigit()):
        prod = await db.products.find_one({"id": int(product_identifier)})
    if not prod and target_str:
        prod = await db.products.find_one({"name": {"$regex": f"^{re.escape(target_str)}$", "$options": "i"}})
    if not prod and target_str:
        prod = await db.products.find_one({"id": target_str})
    if not prod and target_str:
        try:
            from bson import ObjectId
            if ObjectId.is_valid(target_str):
                prod = await db.products.find_one({"_id": ObjectId(target_str)})
        except Exception:
            pass
    if not prod and target_str:
        prod = await db.products.find_one({"sku": {"$regex": f"^{re.escape(target_str)}$", "$options": "i"}})
    if not prod and target_str:
        prod = await db.products.find_one({"name": {"$regex": re.escape(target_str), "$options": "i"}})

    if not prod:
        return False, "product_not_found", "Product not found.", None, None

    prod_id = prod.get("id")
    prod_name = (prod.get("name") or "").strip()

    # 2. Check for duplicate / existing review by this customer for this product
    cust_id = str(customer.get("id") or "").strip()
    cust_email = (customer.get("email") or "").strip().lower()
    cust_name = (customer.get("name") or "").strip()
    cust_phone = (customer.get("phone") or "").strip()

    cust_match = []
    if cust_email:
        cust_match.append({"customer_email": {"$regex": f"^\\s*{re.escape(cust_email)}\\s*$", "$options": "i"}})
    if cust_id:
        cust_match.append({"customer_id": cust_id})
    if cust_name:
        cust_match.append({"name": {"$regex": f"^\\s*{re.escape(cust_name)}\\s*$", "$options": "i"}})

    prod_match = []
    if prod_id is not None:
        prod_match.append({"product_id": prod_id})
        prod_match.append({"product_id": str(prod_id)})
        try:
            prod_match.append({"product_id": int(prod_id)})
        except (ValueError, TypeError):
            pass
    if prod_name:
        prod_match.append({"product": {"$regex": f"^{re.escape(prod_name)}$", "$options": "i"}})
    if target_str:
        prod_match.append({"product": {"$regex": f"^{re.escape(target_str)}$", "$options": "i"}})

    if cust_match and prod_match:
        dup_query = {
            "$and": [
                {"$or": cust_match},
                {"$or": prod_match}
            ]
        }
        existing_rev = await db.reviews.find_one(dup_query)
        if existing_rev:
            return (
                False,
                "already_reviewed",
                "You have already submitted a review for this product. You can edit your existing review.",
                prod,
                clean_doc(existing_rev)
            )

    # 3. Check Orders
    # Direct order lookup if order_id provided
    if order_id:
        order = await db.orders.find_one({"id": {"$regex": f"^\\s*{re.escape(order_id.strip())}\\s*$", "$options": "i"}})
        if order:
            order_status = str(order.get("status") or order.get("order_status") or order.get("orderStatus") or "").strip().lower()
            if any(s in order_status for s in ["delivered", "completed"]):
                items = order.get("items") or order.get("order_items") or order.get("products") or []
                prod_name_clean = prod_name.lower()
                for item in items:
                    item_id = item.get("id") or item.get("productId") or item.get("product_id") or item.get("prod_id")
                    item_name = str(item.get("name") or item.get("product_name") or item.get("title") or item.get("product") or "").strip().lower()

                    if item_id is not None and prod_id is not None and str(item_id).strip() == str(prod_id).strip():
                        return True, "eligible", "Customer is eligible to write a review.", prod, None
                    if prod_name_clean and item_name and (prod_name_clean in item_name or item_name in prod_name_clean):
                        return True, "eligible", "Customer is eligible to write a review.", prod, None

                if not items:
                    return True, "eligible", "Customer is eligible to write a review.", prod, None

    order_clauses = []
    if cust_email:
        order_clauses.append({"email": {"$regex": f"^\\s*{re.escape(cust_email)}\\s*$", "$options": "i"}})
        order_clauses.append({"customer_email": {"$regex": f"^\\s*{re.escape(cust_email)}\\s*$", "$options": "i"}})
        order_clauses.append({"customerEmail": {"$regex": f"^\\s*{re.escape(cust_email)}\\s*$", "$options": "i"}})
    if cust_id:
        order_clauses.append({"customer_id": cust_id})
        order_clauses.append({"customerId": cust_id})
        order_clauses.append({"user_id": cust_id})
    if cust_name:
        order_clauses.append({"customer": {"$regex": f"^\\s*{re.escape(cust_name)}\\s*$", "$options": "i"}})
        name_parts = [p.strip() for p in cust_name.split() if len(p.strip()) >= 3]
        for part in name_parts:
            order_clauses.append({"customer": {"$regex": f"\\b{re.escape(part)}\\b", "$options": "i"}})
    if cust_phone and len(cust_phone) >= 7:
        order_clauses.append({"phone": {"$regex": re.escape(cust_phone), "$options": "i"}})

    orders = await db.orders.find({"$or": order_clauses} if order_clauses else {}).to_list(length=1000)

    for order in orders:
        order_status = str(order.get("status") or order.get("order_status") or order.get("orderStatus") or "").strip().lower()
        payment_status = str(order.get("paymentStatus") or order.get("payment_status") or "").strip().lower()
        payment_method = str(order.get("paymentMethod") or order.get("payment_method") or "").strip().lower()

        # Cancelled orders never qualify
        if order_status in ["cancelled", "canceled"]:
            continue

        # Delivery & payment verification:
        # a) Order marked Delivered or Completed qualifies for customer reviews
        is_delivered = any(s in order_status for s in ["delivered", "completed"])

        # b) Payment status verification
        if payment_status == "failed" and not is_delivered:
            continue

        is_paid = (payment_status == "paid") or (order.get("paymentStatus") is None and is_delivered)
        is_cod = ("cash on delivery" in payment_method or payment_method == "cod")
        is_completed_cod = is_cod and (is_delivered or payment_status == "paid")

        if not (is_delivered or is_paid or is_completed_cod):
            continue

        # Verify product is in order items
        prod_name_clean = prod_name.lower()
        items = order.get("items") or order.get("order_items") or order.get("products") or []
        for item in items:
            item_id = item.get("id") or item.get("productId") or item.get("product_id") or item.get("prod_id")
            item_name = str(item.get("name") or item.get("product_name") or item.get("title") or item.get("product") or "").strip().lower()

            # ID match
            id_matched = False
            if item_id is not None and prod_id is not None:
                if str(item_id).strip() == str(prod_id).strip():
                    id_matched = True

            # Name match (handles variants appended like 'Minimal Diamond Ring - Size 7')
            name_matched = False
            if prod_name_clean and item_name:
                if prod_name_clean == item_name or prod_name_clean in item_name or item_name in prod_name_clean:
                    name_matched = True

            # SKU match if available
            sku_matched = False
            item_sku = str(item.get("sku") or "").strip().lower()
            prod_sku = str(prod.get("sku") or "").strip().lower()
            if item_sku and prod_sku and item_sku == prod_sku:
                sku_matched = True

            if id_matched or name_matched or sku_matched:
                return True, "eligible", "Customer is eligible to write a review.", prod, None

        # If order was marked delivered and has no item breakdown
        if is_delivered and not items:
            return True, "eligible", "Customer is eligible to write a review.", prod, None

    return False, "not_purchased", "Only customers who have purchased this product can write a review.", prod, None


@router.get("/eligibility", response_model=ReviewEligibilityResponse)
async def check_review_eligibility_endpoint(
    product_id: Optional[str] = Query(None),
    product: Optional[str] = Query(None),
    order_id: Optional[str] = Query(None),
    customer: Optional[dict] = Depends(get_current_customer_optional)
):
    """
    Check if the current authenticated customer is eligible to review the specified product.
    Returns structured eligibility status, reason code, and UI guidance.
    """
    db = get_database()
    target = product_id if product_id is not None else product
    if not target:
        raise HTTPException(status_code=400, detail="product_id or product query parameter is required.")

    if not customer:
        return ReviewEligibilityResponse(
            eligible=False,
            can_review=False,
            can_edit=False,
            reason="login_required",
            message="Only customers who have purchased this product can write a review. Please sign in to your account.",
            customer_name=None,
            customer_email=None,
            product_id=target,
            product_name=None,
            existing_review=None
        )

    eligible, reason, message, prod, existing_rev = await check_customer_review_eligibility(
        db=db,
        customer=customer,
        product_identifier=target,
        order_id=order_id
    )

    can_edit = bool(existing_rev)

    return ReviewEligibilityResponse(
        eligible=eligible,
        can_review=eligible,
        can_edit=can_edit,
        reason=reason,
        message=message,
        customer_name=customer.get("name"),
        customer_email=customer.get("email"),
        product_id=prod.get("id") if prod else target,
        product_name=prod.get("name") if prod else None,
        existing_review=existing_rev
    )


@router.get("", response_model=List[ReviewOut])
async def get_reviews(
    approved_only: Optional[bool] = Query(None),
    product: Optional[str] = Query(None),
    product_id: Optional[str] = Query(None),
    admin: Optional[dict] = Depends(get_current_admin_optional)
):
    """
    Retrieve reviews.
    Public storefront callers only receive approved reviews.
    Authenticated admins can view all reviews or filter by approval status.
    """
    db = get_database()
    query = {}

    # Storefront viewers only see approved reviews
    if not admin or approved_only is True:
        query["approved"] = True
    elif approved_only is False:
        pass  # Admin explicitly requested unapproved/all

    if product_id:
        try:
            pid_int = int(product_id)
            query["$or"] = [{"product_id": pid_int}, {"product_id": str(product_id)}]
        except ValueError:
            query["product_id"] = product_id
    elif product and product.lower() != "all":
        query["product"] = {"$regex": f"^{re.escape(product)}$", "$options": "i"}

    items = await db.reviews.find(query).sort("id", -1).to_list(length=1000)
    return clean_docs(items)


@router.post("", response_model=ReviewOut, status_code=201)
async def add_review(
    payload: ReviewCreate,
    admin: Optional[dict] = Depends(get_current_admin_optional),
    customer: Optional[dict] = Depends(get_current_customer_optional)
):
    """
    Submit a review.
    - Admins can add reviews directly (approved status can be defined by admin).
    - Customers must be authenticated and have an eligible completed/paid order for the product.
    - Customer submissions always default to approved=False pending admin moderation.
    """
    db = get_database()
    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()
    formatted_date = payload.date or now.strftime("%d %b %Y")

    if not admin and not customer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to your customer account to submit a review."
        )

    # 1. Admin direct creation
    if admin:
        if payload.id:
            rid = payload.id
        else:
            last = await db.reviews.find({}).sort("id", -1).limit(1).to_list(1)
            rid = (last[0]["id"] + 1) if last else 1

        doc = {
            "id": rid,
            "name": payload.name or admin.get("name", "Admin"),
            "rating": max(1, min(5, int(payload.rating))) if payload.rating else 5,
            "text": payload.text.strip(),
            "date": formatted_date,
            "verified": bool(payload.verified) if payload.verified is not None else True,
            "approved": bool(payload.approved) if payload.approved is not None else True,
            "product": payload.product or "General",
            "product_id": payload.product_id,
            "customer_id": None,
            "customer_email": None,
            "order_id": payload.order_id,
            "created_at": now_iso
        }
        await db.reviews.insert_one(doc)
        return clean_doc(doc)

    # 2. Customer submission with authoritative verification
    target_identifier = payload.product_id if payload.product_id is not None else payload.product
    if not target_identifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product ID or product name is required to submit a review."
        )

    if not payload.text or not payload.text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Review text cannot be empty."
        )

    eligible, reason, message, prod, existing_rev = await check_customer_review_eligibility(
        db=db,
        customer=customer,
        product_identifier=target_identifier
    )

    if not eligible:
        if reason == "already_reviewed":
            # If customer provided review ID matching their existing review, treat as update
            if payload.id and existing_rev and payload.id == existing_rev.get("id"):
                return await update_review(
                    review_id=payload.id,
                    payload=ReviewUpdate(
                        id=payload.id,
                        rating=payload.rating,
                        text=payload.text,
                        name=payload.name
                    ),
                    admin=None,
                    customer=customer
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already submitted a review for this product. You can edit your existing review."
            )
        elif reason == "not_purchased":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only customers who have purchased this product can write a review."
            )
        elif reason == "product_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=message
            )

    # Assign next review ID
    last = await db.reviews.find({}).sort("id", -1).limit(1).to_list(1)
    rid = (last[0]["id"] + 1) if last else 1

    rating = max(1, min(5, int(payload.rating))) if payload.rating else 5
    cust_display_name = (customer.get("name") or payload.name or "Verified Customer").strip()

    doc = {
        "id": rid,
        "name": cust_display_name,
        "rating": rating,
        "text": payload.text.strip(),
        "date": formatted_date,
        "verified": True,
        "approved": False,  # Strict: pending admin moderation
        "product": prod["name"],
        "product_id": prod["id"],
        "customer_id": str(customer.get("id")),
        "customer_email": customer.get("email"),
        "order_id": payload.order_id,
        "created_at": now_iso
    }
    await db.reviews.insert_one(doc)
    return clean_doc(doc)


@router.put("/{review_id}", response_model=ReviewOut)
async def update_review(
    review_id: int,
    payload: ReviewUpdate,
    admin: Optional[dict] = Depends(get_current_admin_optional),
    customer: Optional[dict] = Depends(get_current_customer_optional)
):
    """
    Update a review.
    - Admins can update any review directly.
    - Logged-in customers can edit and update their own submitted reviews for delivered products.
    """
    if not admin and not customer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to edit a review."
        )

    db = get_database()
    existing = await db.reviews.find_one({"id": review_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Review not found.")

    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()
    formatted_date = payload.date or now.strftime("%d %b %Y")

    if customer and not admin:
        cust_email = (customer.get("email") or "").strip().lower()
        cust_id = str(customer.get("id") or "").strip()
        cust_name = (customer.get("name") or "").strip().lower()

        rev_email = str(existing.get("customer_email") or "").strip().lower()
        rev_id = str(existing.get("customer_id") or "").strip()
        rev_name = str(existing.get("name") or "").strip().lower()

        is_owner = False
        if rev_email and cust_email and rev_email == cust_email:
            is_owner = True
        elif rev_id and cust_id and rev_id == cust_id:
            is_owner = True
        elif rev_name and cust_name and rev_name == cust_name:
            is_owner = True
        elif not rev_email and not rev_id:
            if cust_name and rev_name and (cust_name in rev_name or rev_name in cust_name):
                is_owner = True

        if not is_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only edit your own reviews."
            )

        update_data = {
            "date": formatted_date,
            "updated_at": now_iso,
            "approved": False  # Re-submitted review enters moderation
        }
        if payload.rating is not None:
            update_data["rating"] = max(1, min(5, int(payload.rating)))
        if payload.text is not None:
            if not payload.text.strip():
                raise HTTPException(status_code=400, detail="Review text cannot be empty.")
            update_data["text"] = payload.text.strip()
        if payload.name:
            update_data["name"] = payload.name.strip()

        if not existing.get("customer_email") and customer.get("email"):
            update_data["customer_email"] = customer.get("email")
        if not existing.get("customer_id") and customer.get("id"):
            update_data["customer_id"] = str(customer.get("id"))

        await db.reviews.update_one({"id": review_id}, {"$set": update_data})
        updated = await db.reviews.find_one({"id": review_id})
        return clean_doc(updated)

    # Admin update
    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    update_data["updated_at"] = now_iso
    if update_data:
        await db.reviews.update_one({"id": review_id}, {"$set": update_data})

    updated = await db.reviews.find_one({"id": review_id})
    return clean_doc(updated)


@router.put("", response_model=ReviewOut)
async def update_review_by_product(
    payload: ReviewUpdate,
    admin: Optional[dict] = Depends(get_current_admin_optional),
    customer: Optional[dict] = Depends(get_current_customer_optional)
):
    """
    Allow customers or admins to update a review directly by specifying the review ID
    or product ID in the request body.
    """
    if not admin and not customer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to edit a review."
        )

    db = get_database()
    review = None
    if payload.id:
        review = await db.reviews.find_one({"id": payload.id})

    if not review and customer:
        cust_email = (customer.get("email") or "").strip().lower()
        target_prod = payload.product_id if payload.product_id is not None else payload.product
        if target_prod:
            prod_query = [{"product_id": target_prod}, {"product_id": str(target_prod)}]
            try:
                prod_query.append({"product_id": int(target_prod)})
            except (ValueError, TypeError):
                pass
            if payload.product:
                prod_query.append({"product": {"$regex": f"^{re.escape(str(payload.product).strip())}$", "$options": "i"}})

            review = await db.reviews.find_one({
                "$and": [
                    {"customer_email": {"$regex": f"^\\s*{re.escape(cust_email)}\\s*$", "$options": "i"}},
                    {"$or": prod_query}
                ]
            })

    if not review:
        raise HTTPException(status_code=404, detail="Review to update was not found.")

    return await update_review(review_id=review["id"], payload=payload, admin=admin, customer=customer)


@router.patch("/{review_id}/status", response_model=ReviewOut)
async def toggle_review_status(review_id: int, payload: ReviewStatusUpdate, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.reviews.find_one({"id": review_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Review not found.")

    await db.reviews.update_one({"id": review_id}, {"$set": {"approved": payload.approved}})
    updated = await db.reviews.find_one({"id": review_id})
    return clean_doc(updated)


@router.delete("/{review_id}")
async def delete_review(review_id: int, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.reviews.find_one({"id": review_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Review not found.")

    await db.reviews.delete_one({"id": review_id})
    return {"success": True, "message": f"Review {review_id} deleted."}

