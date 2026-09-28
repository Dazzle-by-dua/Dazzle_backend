import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from app.database import get_database, clean_doc, clean_docs
from app.models.schemas import ReviewOut, ReviewCreate, ReviewUpdate, ReviewStatusUpdate
from app.security import get_current_admin

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])

@router.get("", response_model=List[ReviewOut])
async def get_reviews(
    approved_only: Optional[bool] = Query(False),
    product: Optional[str] = Query(None)
):
    db = get_database()
    query = {}
    if approved_only:
        query["approved"] = True

    if product and product.lower() != "all":
        query["product"] = {"$regex": f"^{product}$", "$options": "i"}

    items = await db.reviews.find(query).sort("id", -1).to_list(length=1000)
    return clean_docs(items)

@router.post("", response_model=ReviewOut, status_code=201)
async def add_review(payload: ReviewCreate):
    db = get_database()
    now = datetime.datetime.now()
    now_iso = now.isoformat()
    formatted_date = payload.date or now.strftime("%d %b %Y")

    if payload.id:
        rid = payload.id
    else:
        last = await db.reviews.find({}).sort("id", -1).limit(1).to_list(1)
        rid = (last[0]["id"] + 1) if last else 1

    doc = {
        "id": rid,
        "name": payload.name or "Anonymous",
        "rating": int(payload.rating) if payload.rating else 5,
        "text": payload.text,
        "date": formatted_date,
        "verified": bool(payload.verified),
        "approved": bool(payload.approved),
        "product": payload.product or "General",
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
