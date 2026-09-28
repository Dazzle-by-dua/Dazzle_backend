from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from app.database import get_db, sync_category_counts
from app.models.schemas import CategoryOut, CategoryCreate, CategoryUpdate
from app.security import get_current_admin

router = APIRouter(prefix="/api/categories", tags=["Categories"])

@router.get("", response_model=List[CategoryOut])
def get_categories():
    sync_category_counts()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories;")
        rows = cursor.fetchall()
        return [{"id": r["id"], "name": r["name"], "count": r["count"], "img": r["img"], "desc": r["desc"]} for r in rows]

@router.get("/{cat_id}", response_model=CategoryOut)
def get_category_by_id(cat_id: str):
    sync_category_counts()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories WHERE id = ?", (cat_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Category not found.")
        return {"id": row["id"], "name": row["name"], "count": row["count"], "img": row["img"], "desc": row["desc"]}

@router.post("", response_model=CategoryOut, status_code=201)
def add_category(payload: CategoryCreate, admin: dict = Depends(get_current_admin)):
    clean_id = payload.id.strip().lower().replace(" ", "-")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM categories WHERE id = ?", (clean_id,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail=f"Category with id '{clean_id}' already exists.")

        cursor.execute(
            """INSERT INTO categories (id, name, count, img, desc)
               VALUES (?, ?, ?, ?, ?)""",
            (clean_id, payload.name, payload.count or 0, payload.img or "product_flower_necklace.jpg", payload.desc or "")
        )
    sync_category_counts()
    return get_category_by_id(clean_id)

@router.put("/{cat_id}", response_model=CategoryOut)
def update_category(cat_id: str, payload: CategoryUpdate, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories WHERE id = ?", (cat_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Category not found.")

        updated_name = payload.name if payload.name is not None else row["name"]
        updated_count = payload.count if payload.count is not None else row["count"]
        updated_img = payload.img if payload.img is not None else row["img"]
        updated_desc = payload.desc if payload.desc is not None else row["desc"]

        cursor.execute(
            """UPDATE categories SET name = ?, count = ?, img = ?, desc = ? WHERE id = ?""",
            (updated_name, updated_count, updated_img, updated_desc, cat_id)
        )
    sync_category_counts()
    return get_category_by_id(cat_id)

@router.delete("/{cat_id}")
def delete_category(cat_id: str, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories WHERE id = ?", (cat_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Category not found.")

        cursor.execute("DELETE FROM categories WHERE id = ?", (cat_id,))

    return {"success": True, "message": f"Category '{cat_id}' deleted successfully."}
