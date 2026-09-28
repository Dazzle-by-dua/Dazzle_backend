from typing import List
from fastapi import APIRouter, HTTPException, Depends
from app.database import get_database, clean_doc, clean_docs, sync_category_counts
from app.models.schemas import CategoryOut, CategoryCreate, CategoryUpdate
from app.security import get_current_admin

router = APIRouter(prefix="/api/categories", tags=["Categories"])

@router.get("", response_model=List[CategoryOut])
async def get_categories():
    await sync_category_counts()
    db = get_database()
    cats = await db.categories.find({}).to_list(length=100)
    return clean_docs(cats)

@router.get("/{cat_id}", response_model=CategoryOut)
async def get_category_by_id(cat_id: str):
    await sync_category_counts()
    db = get_database()
    cat = await db.categories.find_one({"id": cat_id})
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found.")
    return clean_doc(cat)

@router.post("", response_model=CategoryOut, status_code=201)
async def add_category(payload: CategoryCreate, admin: dict = Depends(get_current_admin)):
    clean_id = payload.id.strip().lower().replace(" ", "-")
    db = get_database()

    existing = await db.categories.find_one({"id": clean_id})
    if existing:
        raise HTTPException(status_code=400, detail=f"Category with id '{clean_id}' already exists.")

    doc = {
        "id": clean_id,
        "name": payload.name,
        "count": int(payload.count or 0),
        "img": payload.img or "product_flower_necklace.jpg",
        "desc": payload.desc or ""
    }
    await db.categories.insert_one(doc)
    await sync_category_counts()
    return clean_doc(doc)

@router.put("/{cat_id}", response_model=CategoryOut)
async def update_category(cat_id: str, payload: CategoryUpdate, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.categories.find_one({"id": cat_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found.")

    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if update_data:
        await db.categories.update_one({"id": cat_id}, {"$set": update_data})

    await sync_category_counts()
    updated = await db.categories.find_one({"id": cat_id})
    return clean_doc(updated)

@router.delete("/{cat_id}")
async def delete_category(cat_id: str, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.categories.find_one({"id": cat_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found.")

    await db.categories.delete_one({"id": cat_id})
    return {"success": True, "message": f"Category '{cat_id}' deleted successfully."}
