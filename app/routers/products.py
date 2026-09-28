import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from app.database import get_database, clean_doc, clean_docs, sync_category_counts
from app.models.schemas import ProductOut, ProductCreate, ProductUpdate, ProductStockUpdate
from app.security import get_current_admin

router = APIRouter(prefix="/api/products", tags=["Products"])

@router.get("", response_model=List[ProductOut])
async def get_products(
    category: Optional[str] = Query(None),
    inStock: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    sort: Optional[str] = Query("newest")
):
    db = get_database()
    query = {}

    if category and category.lower() != "all":
        query["category"] = {"$regex": f"^{category}$", "$options": "i"}

    if inStock is not None:
        query["inStock"] = inStock

    if search:
        regex_term = {"$regex": search, "$options": "i"}
        query["$or"] = [{"name": regex_term}, {"description": regex_term}, {"sku": regex_term}]

    cursor = db.products.find(query)

    if sort == "price_asc":
        cursor = cursor.sort("price", 1)
    elif sort == "price_desc":
        cursor = cursor.sort("price", -1)
    elif sort == "rating":
        cursor = cursor.sort("rating", -1)
    else:
        cursor = cursor.sort("id", -1)

    items = await cursor.to_list(length=1000)
    return clean_docs(items)

@router.get("/details/map")
async def get_product_details_map():
    db = get_database()
    items = await db.products.find({}).to_list(length=1000)
    details_map = {}
    for r in items:
        p = clean_doc(r)
        details_map[str(p["id"])] = {
            "description": p.get("description") or "An iconic piece from Dazzle by Dua crafted with timeless grace.",
            "material": p.get("material") or "18K Champagne Gold Vermeil",
            "dimensions": p.get("dimensions") or "Standard Fine Jewellery Sizing",
            "sku": p.get("sku") or f"DBD-{p['id']}",
            "variants": p.get("variants") or ["18K Champagne Gold"],
            "images": p.get("images") if p.get("images") else [p.get("img"), "featured_collection.jpg"]
        }
    return details_map

@router.get("/{product_id}", response_model=ProductOut)
async def get_product_by_id(product_id: int):
    db = get_database()
    item = await db.products.find_one({"id": product_id})
    if not item:
        raise HTTPException(status_code=404, detail=f"Product with ID {product_id} not found.")
    return clean_doc(item)

@router.post("", response_model=ProductOut, status_code=201)
async def add_product(payload: ProductCreate, admin: dict = Depends(get_current_admin)):
    db = get_database()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if payload.id:
        pid = payload.id
    else:
        last = await db.products.find({}).sort("id", -1).limit(1).to_list(1)
        pid = (last[0]["id"] + 1) if last else 1

    sku = payload.sku or f"DBD-{payload.category[:2].upper()}-{str(pid).zfill(3)}"
    variants = payload.variants if payload.variants else ["18K Champagne Gold"]
    images = payload.images if payload.images else ([payload.img] if payload.img else ["product_flower_necklace.jpg"])

    doc = {
        "id": pid,
        "name": payload.name,
        "price": float(payload.price),
        "oldPrice": float(payload.oldPrice) if payload.oldPrice is not None else None,
        "category": payload.category,
        "rating": float(payload.rating) if payload.rating else 5.0,
        "reviews": int(payload.reviews) if payload.reviews else 0,
        "img": payload.img or "product_flower_necklace.jpg",
        "badges": list(payload.badges or []),
        "inStock": bool(payload.inStock),
        "sku": sku,
        "material": payload.material,
        "dimensions": payload.dimensions,
        "description": payload.description,
        "variants": list(variants),
        "images": list(images),
        "created_at": now_iso,
        "updated_at": now_iso
    }

    await db.products.insert_one(doc)
    await sync_category_counts()
    return clean_doc(doc)

@router.put("/{product_id}", response_model=ProductOut)
async def update_product(product_id: int, payload: ProductUpdate, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.products.find_one({"id": product_id})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Product with ID {product_id} not found.")

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    update_data["updated_at"] = now_iso

    await db.products.update_one({"id": product_id}, {"$set": update_data})
    updated = await db.products.find_one({"id": product_id})
    await sync_category_counts()
    return clean_doc(updated)

@router.patch("/{product_id}/stock", response_model=ProductOut)
async def toggle_stock(product_id: int, payload: ProductStockUpdate, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.products.find_one({"id": product_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Product not found.")

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    await db.products.update_one(
        {"id": product_id},
        {"$set": {"inStock": payload.inStock, "updated_at": now_iso}}
    )
    updated = await db.products.find_one({"id": product_id})
    return clean_doc(updated)

@router.delete("/{product_id}")
async def delete_product(product_id: int, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.products.find_one({"id": product_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Product not found.")

    await db.products.delete_one({"id": product_id})
    await sync_category_counts()
    return {"success": True, "message": f"Product {product_id} deleted successfully."}
