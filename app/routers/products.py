import json
import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from app.database import get_db, sync_category_counts
from app.models.schemas import ProductOut, ProductCreate, ProductUpdate, ProductStockUpdate
from app.security import get_current_admin

router = APIRouter(prefix="/api/products", tags=["Products"])

def _row_to_product(r) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "price": r["price"],
        "oldPrice": r["oldPrice"],
        "category": r["category"],
        "rating": r["rating"],
        "reviews": r["reviews"],
        "img": r["img"],
        "badges": json.loads(r["badges"]) if r["badges"] else [],
        "inStock": bool(r["inStock"]),
        "sku": r["sku"],
        "material": r["material"],
        "dimensions": r["dimensions"],
        "description": r["description"],
        "variants": json.loads(r["variants"]) if r["variants"] else [],
        "images": json.loads(r["images"]) if r["images"] else []
    }

@router.get("", response_model=List[ProductOut])
def get_products(
    category: Optional[str] = Query(None),
    inStock: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    sort: Optional[str] = Query("newest")
):
    query = "SELECT * FROM products WHERE 1=1"
    params = []

    if category and category.lower() != "all":
        query += " AND LOWER(category) = ?"
        params.append(category.lower())

    if inStock is not None:
        query += " AND inStock = ?"
        params.append(1 if inStock else 0)

    if search:
        query += " AND (LOWER(name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(sku) LIKE ?)"
        term = f"%{search.lower()}%"
        params.extend([term, term, term])

    if sort == "price_asc":
        query += " ORDER BY price ASC"
    elif sort == "price_desc":
        query += " ORDER BY price DESC"
    elif sort == "rating":
        query += " ORDER BY rating DESC"
    else:
        query += " ORDER BY id DESC"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [_row_to_product(r) for r in rows]

@router.get("/details/map")
def get_product_details_map():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products;")
        rows = cursor.fetchall()
        details_map = {}
        for r in rows:
            p = _row_to_product(r)
            details_map[str(p["id"])] = {
                "description": p["description"] or "An iconic piece from Dazzle by Dua crafted with timeless grace.",
                "material": p["material"] or "18K Champagne Gold Vermeil",
                "dimensions": p["dimensions"] or "Standard Fine Jewellery Sizing",
                "sku": p["sku"] or f"DBD-{p['id']}",
                "variants": p["variants"] or ["18K Champagne Gold"],
                "images": p["images"] if p["images"] else [p["img"], "featured_collection.jpg"]
            }
        return details_map

@router.get("/{product_id}", response_model=ProductOut)
def get_product_by_id(product_id: int):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Product with ID {product_id} not found.")
        return _row_to_product(row)

@router.post("", response_model=ProductOut, status_code=201)
def add_product(payload: ProductCreate, admin: dict = Depends(get_current_admin)):
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()

        if payload.id:
            pid = payload.id
        else:
            cursor.execute("SELECT COALESCE(MAX(id), 0) FROM products;")
            pid = cursor.fetchone()[0] + 1

        sku = payload.sku or f"DBD-{payload.category[:2].upper()}-{str(pid).zfill(3)}"
        variants = payload.variants if payload.variants else ["18K Champagne Gold"]
        images = payload.images if payload.images else ([payload.img] if payload.img else ["product_flower_necklace.jpg"])

        cursor.execute(
            """INSERT INTO products (id, name, price, oldPrice, category, rating, reviews, img, badges, inStock, sku, material, dimensions, description, variants, images, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid,
                payload.name,
                payload.price,
                payload.oldPrice,
                payload.category,
                payload.rating or 5.0,
                payload.reviews or 0,
                payload.img or "product_flower_necklace.jpg",
                json.dumps(payload.badges or []),
                1 if payload.inStock else 0,
                sku,
                payload.material,
                payload.dimensions,
                payload.description,
                json.dumps(variants),
                json.dumps(images),
                now_iso,
                now_iso
            )
        )
        cursor.execute("SELECT * FROM products WHERE id = ?", (pid,))
        new_row = cursor.fetchone()

    sync_category_counts()
    return _row_to_product(new_row)

@router.put("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, payload: ProductUpdate, admin: dict = Depends(get_current_admin)):
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=f"Product with ID {product_id} not found.")

        current = _row_to_product(existing)

        updated_name = payload.name if payload.name is not None else current["name"]
        updated_price = payload.price if payload.price is not None else current["price"]
        updated_old_price = payload.oldPrice if payload.oldPrice is not None else current["oldPrice"]
        updated_category = payload.category if payload.category is not None else current["category"]
        updated_rating = payload.rating if payload.rating is not None else current["rating"]
        updated_reviews = payload.reviews if payload.reviews is not None else current["reviews"]
        updated_img = payload.img if payload.img is not None else current["img"]
        updated_badges = payload.badges if payload.badges is not None else current["badges"]
        updated_in_stock = 1 if (payload.inStock if payload.inStock is not None else current["inStock"]) else 0
        updated_sku = payload.sku if payload.sku is not None else current["sku"]
        updated_material = payload.material if payload.material is not None else current["material"]
        updated_dimensions = payload.dimensions if payload.dimensions is not None else current["dimensions"]
        updated_description = payload.description if payload.description is not None else current["description"]
        updated_variants = payload.variants if payload.variants is not None else current["variants"]
        updated_images = payload.images if payload.images is not None else current["images"]

        cursor.execute(
            """UPDATE products
               SET name = ?, price = ?, oldPrice = ?, category = ?, rating = ?, reviews = ?, img = ?, badges = ?, inStock = ?, sku = ?, material = ?, dimensions = ?, description = ?, variants = ?, images = ?, updated_at = ?
               WHERE id = ?""",
            (
                updated_name,
                updated_price,
                updated_old_price,
                updated_category,
                updated_rating,
                updated_reviews,
                updated_img,
                json.dumps(updated_badges),
                updated_in_stock,
                updated_sku,
                updated_material,
                updated_dimensions,
                updated_description,
                json.dumps(updated_variants),
                json.dumps(updated_images),
                now_iso,
                product_id
            )
        )
        cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = cursor.fetchone()

    sync_category_counts()
    return _row_to_product(row)

@router.patch("/{product_id}/stock", response_model=ProductOut)
def toggle_stock(product_id: int, payload: ProductStockUpdate, admin: dict = Depends(get_current_admin)):
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Product not found.")

        cursor.execute(
            "UPDATE products SET inStock = ?, updated_at = ? WHERE id = ?",
            (1 if payload.inStock else 0, now_iso, product_id)
        )
        cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = cursor.fetchone()

    return _row_to_product(row)

@router.delete("/{product_id}")
def delete_product(product_id: int, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Product not found.")

        cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))

    sync_category_counts()
    return {"success": True, "message": f"Product {product_id} deleted successfully."}
