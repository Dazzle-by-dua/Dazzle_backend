import random
from typing import List
from fastapi import APIRouter, HTTPException, Depends
from app.database import get_database, clean_doc, clean_docs
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

@router.get("", response_model=OffersOut)
async def get_all_offers():
    db = get_database()
    coupons = await db.coupons.find({}).to_list(length=100)
    combos = await db.combos.find({}).to_list(length=100)
    return {"coupons": clean_docs(coupons), "combos": clean_docs(combos)}

@router.put("", response_model=OffersOut)
async def update_all_offers(payload: dict, admin: dict = Depends(get_current_admin)):
    db = get_database()
    coupons = payload.get("coupons", [])
    combos = payload.get("combos", [])
    if coupons:
        await db.coupons.delete_many({})
        for c in coupons:
            c_doc = {k: v for k, v in c.items() if k != "_id"}
            await db.coupons.insert_one(c_doc)
    if combos:
        await db.combos.delete_many({})
        for cb in combos:
            cb_doc = {k: v for k, v in cb.items() if k != "_id"}
            await db.combos.insert_one(cb_doc)
    fresh_coupons = await db.coupons.find({}).to_list(100)
    fresh_combos = await db.combos.find({}).to_list(100)
    return {"coupons": clean_docs(fresh_coupons), "combos": clean_docs(fresh_combos)}


# Coupons Endpoints
@router.get("/coupons", response_model=List[CouponOut])
async def get_coupons():
    db = get_database()
    coupons = await db.coupons.find({}).to_list(length=100)
    return clean_docs(coupons)

@router.post("/coupons", response_model=CouponOut, status_code=201)
async def add_coupon(payload: CouponCreate, admin: dict = Depends(get_current_admin)):
    clean_code = payload.code.strip().upper()
    db = get_database()

    existing = await db.coupons.find_one({"code": clean_code})
    if existing:
        raise HTTPException(status_code=400, detail=f"Coupon code '{clean_code}' already exists.")

    cid = payload.id or f"c_{clean_code.lower()}_{random.randint(10, 99)}"
    doc = {
        "id": cid,
        "code": clean_code,
        "title": payload.title,
        "discount": float(payload.discount),
        "type": payload.type or "percent",
        "minOrder": float(payload.minOrder or 0),
        "expiry": payload.expiry or "2026-12-31",
        "desc": payload.desc,
        "badge": payload.badge,
        "active": bool(payload.active)
    }
    await db.coupons.insert_one(doc)
    return clean_doc(doc)

@router.put("/coupons/{coupon_id}", response_model=CouponOut)
async def update_coupon(coupon_id: str, payload: CouponUpdate, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.coupons.find_one({"id": coupon_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Coupon not found.")

    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if "code" in update_data:
        update_data["code"] = update_data["code"].strip().upper()

    if update_data:
        await db.coupons.update_one({"id": coupon_id}, {"$set": update_data})

    updated = await db.coupons.find_one({"id": coupon_id})
    return clean_doc(updated)

@router.delete("/coupons/{coupon_id}")
async def delete_coupon(coupon_id: str, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.coupons.find_one({"id": coupon_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Coupon not found.")

    await db.coupons.delete_one({"id": coupon_id})
    return {"success": True, "message": f"Coupon {coupon_id} deleted."}

@router.post("/coupons/validate", response_model=ValidateCouponResponse)
async def validate_coupon(payload: ValidateCouponRequest):
    code_clean = (payload.code or "").strip().upper()
    db = get_database()
    row = await db.coupons.find_one({"code": code_clean, "active": True})
    if not row:
        row = await db.offers.find_one({"code": code_clean, "active": True})
    if not row:
        from app.seed_data import DEFAULT_OFFERS
        for def_c in DEFAULT_OFFERS.get("coupons", []):
            if def_c.get("code") == code_clean and def_c.get("active", True):
                row = def_c
                break

    # Canonical fallback for built-in FREEDEL coupon
    if not row and code_clean == "FREEDEL":
        row = {
            "id": "c_freedel",
            "code": "FREEDEL",
            "title": "Free Delivery",
            "discount": 0.0,
            "type": "free_delivery",
            "minOrder": 0.0,
            "expiry": "2030-12-31",
            "desc": "Enjoy 100% complimentary delivery on your entire order.",
            "badge": "Free Delivery",
            "active": True
        }

    if not row:
        return {
            "valid": False,
            "message": f"Invalid or expired coupon code '{code_clean}'.",
            "discountAmount": 0.0,
            "deliveryDiscount": 0.0,
            "freeShipping": False
        }

    coupon = clean_doc(row)

    min_order = float(coupon.get("minOrder", 0) or 0)
    if payload.orderTotal < min_order:
        return {
            "valid": False,
            "message": f"Order total must be at least ₹{min_order:,.0f} to apply code '{code_clean}'.",
            "discountAmount": 0.0,
            "deliveryDiscount": 0.0,
            "freeShipping": False,
            "coupon": coupon
        }

    discount_amount = 0.0
    delivery_discount = 0.0
    free_shipping = False

    ctype = coupon.get("type", "percent")
    if ctype in ["free_delivery", "free_shipping"] or code_clean == "FREEDEL":
        free_shipping = True
        if payload.deliveryFee is not None and payload.deliveryFee > 0:
            delivery_discount = float(payload.deliveryFee)
        elif payload.city or payload.state or payload.address:
            from app.delivery_rules import calculate_delivery_charge
            try:
                d_info = calculate_delivery_charge(city=payload.city, state=payload.state, address=payload.address)
                delivery_discount = float(d_info.get("delivery_fee", 0.0))
            except Exception:
                delivery_discount = 0.0
        return {
            "valid": True,
            "message": f"Coupon '{coupon['code']}' applied! 100% free delivery.",
            "discountAmount": 0.0,
            "deliveryDiscount": delivery_discount,
            "discountType": ctype,
            "freeShipping": True,
            "coupon": coupon
        }
    elif ctype == "percent":
        discount_amount = round(payload.orderTotal * (float(coupon.get("discount", 0)) / 100.0), 2)
    elif ctype == "fixed":
        discount_amount = min(payload.orderTotal, float(coupon.get("discount", 0)))

    return {
        "valid": True,
        "message": f"Coupon '{coupon['code']}' applied successfully!",
        "discountAmount": discount_amount,
        "deliveryDiscount": 0.0,
        "discountType": ctype,
        "freeShipping": free_shipping,
        "coupon": coupon
    }

# Combos Endpoints
@router.get("/combos", response_model=List[ComboOut])
async def get_combos():
    db = get_database()
    combos = await db.combos.find({}).to_list(length=100)
    return clean_docs(combos)

@router.post("/combos", response_model=ComboOut, status_code=201)
async def add_combo(payload: ComboCreate, admin: dict = Depends(get_current_admin)):
    cid = payload.id or f"cb_{random.randint(100, 999)}"
    db = get_database()

    doc = {
        "id": cid,
        "name": payload.name,
        "discount": payload.discount,
        "price": float(payload.price),
        "oldPrice": float(payload.oldPrice),
        "items": list(payload.items),
        "images": list(payload.images)
    }
    await db.combos.insert_one(doc)
    return clean_doc(doc)

@router.put("/combos/{combo_id}", response_model=ComboOut)
async def update_combo(combo_id: str, payload: ComboUpdate, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.combos.find_one({"id": combo_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Combo not found.")

    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if update_data:
        await db.combos.update_one({"id": combo_id}, {"$set": update_data})

    updated = await db.combos.find_one({"id": combo_id})
    return clean_doc(updated)

@router.delete("/combos/{combo_id}")
async def delete_combo(combo_id: str, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.combos.find_one({"id": combo_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Combo not found.")

    await db.combos.delete_one({"id": combo_id})
    return {"success": True, "message": f"Combo {combo_id} deleted."}
