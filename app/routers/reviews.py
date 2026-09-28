import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from app.database import get_db
from app.models.schemas import ReviewOut, ReviewCreate, ReviewUpdate, ReviewStatusUpdate
from app.security import get_current_admin

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])

def _row_to_review(r) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "rating": r["rating"],
        "text": r["text"],
        "date": r["date"],
        "verified": bool(r["verified"]),
        "approved": bool(r["approved"]),
        "product": r["product"]
    }

@router.get("", response_model=List[ReviewOut])
def get_reviews(
    approved_only: Optional[bool] = Query(False),
    product: Optional[str] = Query(None)
):
    query = "SELECT * FROM reviews WHERE 1=1"
    params = []

    if approved_only:
        query += " AND approved = 1"

    if product and product.lower() != "all":
        query += " AND LOWER(product) = ?"
        params.append(product.lower())

    query += " ORDER BY id DESC"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [_row_to_review(r) for r in rows]

@router.post("", response_model=ReviewOut, status_code=201)
def add_review(payload: ReviewCreate):
    now = datetime.datetime.now()
    now_iso = now.isoformat()
    formatted_date = payload.date or now.strftime("%d %b %Y")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO reviews (name, rating, text, date, verified, approved, product, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload.name or "Anonymous",
                int(payload.rating) if payload.rating else 5,
                payload.text,
                formatted_date,
                1 if payload.verified else 0,
                1 if payload.approved else 0,
                payload.product or "General",
                now_iso
            )
        )
        new_id = cursor.lastrowid
        cursor.execute("SELECT * FROM reviews WHERE id = ?", (new_id,))
        row = cursor.fetchone()

    return _row_to_review(row)

@router.put("/{review_id}", response_model=ReviewOut)
def update_review(review_id: int, payload: ReviewUpdate, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Review not found.")

        updated_name = payload.name if payload.name is not None else row["name"]
        updated_rating = payload.rating if payload.rating is not None else row["rating"]
        updated_text = payload.text if payload.text is not None else row["text"]
        updated_date = payload.date if payload.date is not None else row["date"]
        updated_verified = 1 if (payload.verified if payload.verified is not None else bool(row["verified"])) else 0
        updated_approved = 1 if (payload.approved if payload.approved is not None else bool(row["approved"])) else 0
        updated_product = payload.product if payload.product is not None else row["product"]

        cursor.execute(
            """UPDATE reviews
               SET name = ?, rating = ?, text = ?, date = ?, verified = ?, approved = ?, product = ?
               WHERE id = ?""",
            (updated_name, updated_rating, updated_text, updated_date, updated_verified, updated_approved, updated_product, review_id)
        )
        cursor.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
        new_row = cursor.fetchone()

    return _row_to_review(new_row)

@router.patch("/{review_id}/status", response_model=ReviewOut)
def toggle_review_status(review_id: int, payload: ReviewStatusUpdate, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Review not found.")

        cursor.execute(
            "UPDATE reviews SET approved = ? WHERE id = ?",
            (1 if payload.approved else 0, review_id)
        )
        cursor.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
        row = cursor.fetchone()

    return _row_to_review(row)

@router.delete("/{review_id}")
def delete_review(review_id: int, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Review not found.")

        cursor.execute("DELETE FROM reviews WHERE id = ?", (review_id,))

    return {"success": True, "message": f"Review {review_id} deleted."}
