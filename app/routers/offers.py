import json
import random
from typing import List
from fastapi import APIRouter, HTTPException, Depends
from app.database import get_db
from app.models.schemas import (
    OffersOut,
    CouponOut,
    CouponCreate,
    CouponUpdate,
    ComboOut,
    ComboCreate,
    ComboUpdate,
    ValidateCouponRequest,
    ValidateCouponResponse
)
from app.security import get_current_admin

router = APIRouter(prefix="/api/offers", tags=["Offers & Combos"])

def _row_to_coupon(r) -> dict:
    return {
        "id": r["id"],
        "code": r["code"],
        "title": r["title"],
        "discount": r["discount"],
        "type": r["type"],
        "minOrder": r["minOrder"],
        "expiry": r["expiry"],
        "desc": r["desc"],
        "badge": r["badge"],
        "active": bool(r["active"])
    }

def _row_to_combo(r) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "discount": r["discount"],
        "price": r["price"],
        "oldPrice": r["oldPrice"],
        "items": json.loads(r["items"]) if r["items"] else [],
        "images": json.loads(r["images"]) if r["images"] else []
    }

@router.get("", response_model=OffersOut)
def get_all_offers():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM coupons;")
        coupons = [_row_to_coupon(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM combos;")
        combos = [_row_to_combo(r) for r in cursor.fetchall()]

        return {"coupons": coupons, "combos": combos}

# Coupons Endpoints
@router.get("/coupons", response_model=List[CouponOut])
def get_coupons():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM coupons;")
        return [_row_to_coupon(r) for r in cursor.fetchall()]

@router.post("/coupons", response_model=CouponOut, status_code=201)
def add_coupon(payload: CouponCreate, admin: dict = Depends(get_current_admin)):
    clean_code = payload.code.strip().upper()
    cid = payload.id or f"c_{clean_code.lower()}_{random.randint(10, 99)}"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM coupons WHERE UPPER(code) = ?", (clean_code,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail=f"Coupon code '{clean_code}' already exists.")

        cursor.execute(
            """INSERT INTO coupons (id, code, title, discount, type, minOrder, expiry, desc, badge, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cid,
                clean_code,
                payload.title,
                payload.discount,
                payload.type or "percent",
                payload.minOrder or 0,
                payload.expiry or "2026-12-31",
                payload.desc,
                payload.badge,
                1 if payload.active else 0
            )
        )
        cursor.execute("SELECT * FROM coupons WHERE id = ?", (cid,))
        row = cursor.fetchone()

    return _row_to_coupon(row)

@router.put("/coupons/{coupon_id}", response_model=CouponOut)
def update_coupon(coupon_id: str, payload: CouponUpdate, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM coupons WHERE id = ?", (coupon_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Coupon not found.")

        current = _row_to_coupon(row)

        up_code = (payload.code.strip().upper()) if payload.code is not None else current["code"]
        up_title = payload.title if payload.title is not None else current["title"]
        up_discount = payload.discount if payload.discount is not None else current["discount"]
        up_type = payload.type if payload.type is not None else current["type"]
        up_min_order = payload.minOrder if payload.minOrder is not None else current["minOrder"]
        up_expiry = payload.expiry if payload.expiry is not None else current["expiry"]
        up_desc = payload.desc if payload.desc is not None else current["desc"]
        up_badge = payload.badge if payload.badge is not None else current["badge"]
        up_active = 1 if (payload.active if payload.active is not None else current["active"]) else 0

        cursor.execute(
            """UPDATE coupons
               SET code = ?, title = ?, discount = ?, type = ?, minOrder = ?, expiry = ?, desc = ?, badge = ?, active = ?
               WHERE id = ?""",
            (up_code, up_title, up_discount, up_type, up_min_order, up_expiry, up_desc, up_badge, up_active, coupon_id)
        )
        cursor.execute("SELECT * FROM coupons WHERE id = ?", (coupon_id,))
        new_row = cursor.fetchone()

    return _row_to_coupon(new_row)

@router.delete("/coupons/{coupon_id}")
def delete_coupon(coupon_id: str, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM coupons WHERE id = ?", (coupon_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Coupon not found.")

        cursor.execute("DELETE FROM coupons WHERE id = ?", (coupon_id,))

    return {"success": True, "message": f"Coupon {coupon_id} deleted."}

@router.post("/coupons/validate", response_model=ValidateCouponResponse)
def validate_coupon(payload: ValidateCouponRequest):
    code_clean = payload.code.strip().upper()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM coupons WHERE UPPER(code) = ? AND active = 1", (code_clean,))
        row = cursor.fetchone()

        if not row:
            return {
                "valid": False,
                "message": f"Invalid or expired coupon code '{code_clean}'.",
                "discountAmount": 0.0,
                "freeShipping": False
            }

        coupon = _row_to_coupon(row)

        if payload.orderTotal < coupon["minOrder"]:
            return {
                "valid": False,
                "message": f"Order total must be at least ?{coupon['minOrder']:,.0f} to apply code '{code_clean}'.",
                "discountAmount": 0.0,
                "freeShipping": False,
                "coupon": coupon
            }

        discount_amount = 0.0
        free_shipping = False

        if coupon["type"] == "percent":
            discount_amount = round(payload.orderTotal * (coupon["discount"] / 100.0), 2)
        elif coupon["type"] == "fixed":
            discount_amount = min(payload.orderTotal, coupon["discount"])
        elif coupon["type"] == "free_shipping":
            free_shipping = True

        return {
            "valid": True,
            "message": f"Coupon '{coupon['code']}' applied successfully!",
            "discountAmount": discount_amount,
            "discountType": coupon["type"],
            "freeShipping": free_shipping,
            "coupon": coupon
        }

# Combos Endpoints
@router.get("/combos", response_model=List[ComboOut])
def get_combos():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM combos;")
        return [_row_to_combo(r) for r in cursor.fetchall()]

@router.post("/combos", response_model=ComboOut, status_code=201)
def add_combo(payload: ComboCreate, admin: dict = Depends(get_current_admin)):
    cid = payload.id or f"cb_{random.randint(100, 999)}"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO combos (id, name, discount, price, oldPrice, items, images)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                cid,
                payload.name,
                payload.discount,
                payload.price,
                payload.oldPrice,
                json.dumps(payload.items),
                json.dumps(payload.images)
            )
        )
        cursor.execute("SELECT * FROM combos WHERE id = ?", (cid,))
        row = cursor.fetchone()

    return _row_to_combo(row)

@router.put("/combos/{combo_id}", response_model=ComboOut)
def update_combo(combo_id: str, payload: ComboUpdate, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM combos WHERE id = ?", (combo_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Combo not found.")

        current = _row_to_combo(row)

        up_name = payload.name if payload.name is not None else current["name"]
        up_discount = payload.discount if payload.discount is not None else current["discount"]
        up_price = payload.price if payload.price is not None else current["price"]
        up_old_price = payload.oldPrice if payload.oldPrice is not None else current["oldPrice"]
        up_items = payload.items if payload.items is not None else current["items"]
        up_images = payload.images if payload.images is not None else current["images"]

        cursor.execute(
            """UPDATE combos
               SET name = ?, discount = ?, price = ?, oldPrice = ?, items = ?, images = ?
               WHERE id = ?""",
            (up_name, up_discount, up_price, up_old_price, json.dumps(up_items), json.dumps(up_images), combo_id)
        )
        cursor.execute("SELECT * FROM combos WHERE id = ?", (combo_id,))
        new_row = cursor.fetchone()

    return _row_to_combo(new_row)

@router.delete("/combos/{combo_id}")
def delete_combo(combo_id: str, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM combos WHERE id = ?", (combo_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Combo not found.")

        cursor.execute("DELETE FROM combos WHERE id = ?", (combo_id,))

    return {"success": True, "message": f"Combo {combo_id} deleted."}
