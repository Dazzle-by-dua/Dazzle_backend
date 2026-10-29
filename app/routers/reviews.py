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
    product_identifier: Any
):
    """
    Authoritative backend eligibility verification.
    1. Validates that the product exists.
    2. Enforces one review per customer per product (checks pending & approved reviews).
    3. Searches customer's order records:
       - Disqualifies cancelled orders or failed payments.
       - Requires successful payment (paymentStatus == 'Paid') OR
         completed Cash on Delivery order (status in ['Delivered', 'Completed']).
       - Verifies the product is in the order items.
    Returns: (eligible: bool, reason: str, message: str, product: Optional[dict], existing_review: Optional[dict])
    """
    # 1. Locate Product
    prod = None
    if isinstance(product_identifier, int) or (isinstance(product_identifier, str) and product_identifier.isdigit()):
        prod = await db.products.find_one({"id": int(product_identifier)})
    if not prod and isinstance(product_identifier, str):
        prod = await db.products.find_one({"name": {"$regex": f"^{re.escape(product_identifier.strip())}$", "$options": "i"}})
    if not prod:
        prod = await db.products.find_one({"id": str(product_identifier)})

    if not prod:
        return False, "product_not_found", "Product not found.", None, None

    prod_id = prod.get("id")
    prod_name = prod.get("name", "")

    # 2. Check for duplicate review by this customer for this product
    cust_id = str(customer.get("id") or "")
    cust_email = (customer.get("email") or "").strip().lower()

    dup_query = {
        "$and": [
            {
                "$or": [
                    {"customer_email": {"$regex": f"^{re.escape(cust_email)}$", "$options": "i"}},
                    {"customer_id": cust_id}
                ]
            },
            {
                "$or": [
                    {"product_id": prod_id},
                    {"product_id": str(prod_id)},
                    {"product": {"$regex": f"^{re.escape(prod_name)}$", "$options": "i"}}
                ]
            }
        ]
    }
    existing_rev = await db.reviews.find_one(dup_query)
    if existing_rev:
        return (
            False,
            "already_reviewed",
            "You have already submitted a review for this product. Thank you!",
            prod,
            clean_doc(existing_rev)
        )

    # 3. Check Orders
    order_query = {
        "$or": [
            {"email": {"$regex": f"^{re.escape(cust_email)}$", "$options": "i"}},
            {"customer_id": cust_id}
        ]
    }
    orders = await db.orders.find(order_query).to_list(length=1000)

    for order in orders:
        order_status = str(order.get("status") or "").strip().lower()
        payment_status = str(order.get("paymentStatus") or "").strip().lower() if order.get("paymentStatus") else ""
        payment_method = str(order.get("paymentMethod") or "").strip().lower() if order.get("paymentMethod") else ""

        # Cancelled or failed orders never qualify
        if order_status in ["cancelled", "canceled"]:
            continue
        if payment_status == "failed":
            continue

        # Payment / Completion verification:
        # a) Verified paid order
        is_paid = (payment_status == "paid") or (order.get("paymentStatus") is None and order_status in ["delivered", "completed"])
        # b) Valid completed Cash on Delivery order
        is_cod = ("cash on delivery" in payment_method or payment_method == "cod")
        is_completed_cod = is_cod and (order_status in ["delivered", "completed"] or payment_status == "paid")

        if not (is_paid or is_completed_cod):
            continue

        # Verify product is in order items
        for item in order.get("items", []):
            item_id = item.get("id")
            item_name = item.get("name", "")
            if (item_id is not None and (str(item_id) == str(prod_id))) or (item_name and item_name.strip().lower() == prod_name.strip().lower()):
                return True, "eligible", "Customer is eligible to write a review.", prod, None

    return False, "not_purchased", "Only customers who have purchased this product can write a review.", prod, None


@router.get("/eligibility", response_model=ReviewEligibilityResponse)
async def check_review_eligibility_endpoint(
    product_id: Optional[str] = Query(None),
    product: Optional[str] = Query(None),
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
        product_identifier=target
    )

    return ReviewEligibilityResponse(
        eligible=eligible,
        can_review=eligible,
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already submitted a review for this product."
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
async def update_review(review_id: int, payload: ReviewUpdate, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.reviews.find_one({"id": review_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Review not found.")

    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if update_data:
        await db.reviews.update_one({"id": review_id}, {"$set": update_data})

    updated = await db.reviews.find_one({"id": review_id})
    return clean_doc(updated)


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

