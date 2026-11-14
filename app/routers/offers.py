import random
import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
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


def is_coupon_expired(expiry_str: Optional[str]) -> bool:
    """Check if coupon expiry date is in the past."""
    if not expiry_str or not str(expiry_str).strip():
        return False
    try:
        s = str(expiry_str).strip()[:10]
        exp_date = datetime.date.fromisoformat(s)
        return exp_date < datetime.date.today()
    except Exception:
        return False


def is_coupon_not_yet_active(valid_from_str: Optional[str]) -> bool:
    """Check if coupon start date is in the future."""
    if not valid_from_str or not str(valid_from_str).strip():
        return False
    try:
        s = str(valid_from_str).strip()[:10]
        vf_date = datetime.date.fromisoformat(s)
        return vf_date > datetime.date.today()
    except Exception:
        return False


# Coupons Endpoints
@router.get("/coupons", response_model=List[CouponOut])
async def get_coupons(active_only: bool = Query(False)):
    db = get_database()
    query = {"active": True} if active_only else {}
    coupons = await db.coupons.find(query).to_list(length=100)
    if not coupons:
        from app.seed_data import DEFAULT_OFFERS
        defaults = DEFAULT_OFFERS.get("coupons", [])
        if active_only:
            defaults = [c for c in defaults if c.get("active", True)]
        return defaults
    return clean_docs(coupons)


@router.get("/coupons/public", response_model=List[CouponOut])
@router.get("/coupons/available", response_model=List[CouponOut])
async def get_public_available_coupons():
    """
    Public customer-facing endpoint: returns all active, published coupons.
    Safe for storefront display; does not expose administrative actions.
    """
    db = get_database()
    coupons = await db.coupons.find({"active": True}).to_list(length=100)
    if not coupons:
        from app.seed_data import DEFAULT_OFFERS
        coupons = [c for c in DEFAULT_OFFERS.get("coupons", []) if c.get("active", True)]
    else:
        coupons = clean_docs(coupons)

    # Ensure canonical FREEDEL is included if active
    existing_codes = {c.get("code", "").upper() for c in coupons}
    if "FREEDEL" not in existing_codes:
        coupons.append({
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
        })

    return coupons


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
        "maxDiscount": float(payload.maxDiscount) if payload.maxDiscount is not None else None,
        "expiry": payload.expiry or "2026-12-31",
        "validFrom": payload.validFrom,
        "usageLimit": int(payload.usageLimit) if payload.usageLimit is not None else None,
        "usedCount": int(payload.usedCount or 0),
        "applicableCategories": payload.applicableCategories or [],
        "applicableProducts": payload.applicableProducts or [],
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
    row = await db.coupons.find_one({"code": code_clean})
    if not row:
        row = await db.offers.find_one({"code": code_clean})
    if not row:
        from app.seed_data import DEFAULT_OFFERS
        for def_c in DEFAULT_OFFERS.get("coupons", []):
            if def_c.get("code") == code_clean:
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

    # 1. Active check
    if not coupon.get("active", True):
        return {
            "valid": False,
            "message": f"Coupon code '{code_clean}' is currently inactive or disabled.",
            "discountAmount": 0.0,
            "deliveryDiscount": 0.0,
            "freeShipping": False,
            "coupon": coupon
        }

    # 2. Expiry check
    if is_coupon_expired(coupon.get("expiry")):
        return {
            "valid": False,
            "message": f"Coupon code '{code_clean}' expired on {coupon.get('expiry')}.",
            "discountAmount": 0.0,
            "deliveryDiscount": 0.0,
            "freeShipping": False,
            "coupon": coupon
        }

    # 3. Valid from (start date) check
    if is_coupon_not_yet_active(coupon.get("validFrom")):
        return {
            "valid": False,
            "message": f"Coupon code '{code_clean}' is not active yet. Valid from {coupon.get('validFrom')}.",
            "discountAmount": 0.0,
            "deliveryDiscount": 0.0,
            "freeShipping": False,
            "coupon": coupon
        }

    # 4. Usage limit check
    usage_limit = coupon.get("usageLimit")
    used_count = coupon.get("usedCount", 0) or 0
    if usage_limit is not None and int(used_count) >= int(usage_limit):
        return {
            "valid": False,
            "message": f"Coupon code '{code_clean}' usage limit has been reached.",
            "discountAmount": 0.0,
            "deliveryDiscount": 0.0,
            "freeShipping": False,
            "coupon": coupon
        }

    # 5. Minimum order requirement
    min_order = float(coupon.get("minOrder", 0) or 0)
    if payload.orderTotal < min_order:
        shortfall = min_order - payload.orderTotal
        return {
            "valid": False,
            "message": f"Order total must be at least ₹{min_order:,.0f} to apply code '{code_clean}'. (Add ₹{shortfall:,.0f} more to qualify)",
            "discountAmount": 0.0,
            "deliveryDiscount": 0.0,
            "freeShipping": False,
            "coupon": coupon
        }

    # 6. Category / Product restrictions (if items provided)
    if payload.items and len(payload.items) > 0:
        req_cats = [c.strip().lower() for c in (coupon.get("applicableCategories") or []) if str(c).strip()]
        if req_cats:
            item_cats = [str(it.get("category", "")).strip().lower() for it in payload.items if it.get("category")]
            if not any(c in req_cats for c in item_cats):
                return {
                    "valid": False,
                    "message": f"Coupon code '{code_clean}' is only valid on categories: {', '.join(coupon['applicableCategories'])}.",
                    "discountAmount": 0.0,
                    "deliveryDiscount": 0.0,
                    "freeShipping": False,
                    "coupon": coupon
                }

        req_prods = [str(p).strip().lower() for p in (coupon.get("applicableProducts") or []) if str(p).strip()]
        if req_prods:
            item_ids = [str(it.get("id", "")).strip().lower() for it in payload.items]
            item_names = [str(it.get("name", "")).strip().lower() for it in payload.items]
            if not any(p in item_ids or p in item_names for p in req_prods):
                return {
                    "valid": False,
                    "message": f"Coupon code '{code_clean}' is only valid for selected jewellery pieces.",
                    "discountAmount": 0.0,
                    "deliveryDiscount": 0.0,
                    "freeShipping": False,
                    "coupon": coupon
                }

    # 7. Discount calculation with optional maximum discount cap
    discount_amount = 0.0
    delivery_discount = 0.0
    free_shipping = False
    max_discount = float(coupon["maxDiscount"]) if coupon.get("maxDiscount") is not None else None

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
            "maxDiscount": max_discount,
            "coupon": coupon
        }
    elif ctype == "percent":
        raw_discount = round(payload.orderTotal * (float(coupon.get("discount", 0)) / 100.0), 2)
        if max_discount is not None and max_discount > 0 and raw_discount > max_discount:
            discount_amount = max_discount
            success_msg = f"Coupon '{coupon['code']}' applied! {coupon.get('discount'):g}% off capped at ₹{discount_amount:,.0f}."
        else:
            discount_amount = raw_discount
            success_msg = f"Coupon '{coupon['code']}' applied successfully! You saved ₹{discount_amount:,.0f}."
    elif ctype == "fixed":
        raw_discount = min(payload.orderTotal, float(coupon.get("discount", 0)))
        if max_discount is not None and max_discount > 0 and raw_discount > max_discount:
            discount_amount = max_discount
        else:
            discount_amount = raw_discount
        success_msg = f"Coupon '{coupon['code']}' applied successfully! You saved ₹{discount_amount:,.0f}."
    else:
        discount_amount = 0.0
        success_msg = f"Coupon '{coupon['code']}' applied successfully!"

    return {
        "valid": True,
        "message": success_msg,
        "discountAmount": discount_amount,
        "deliveryDiscount": 0.0,
        "discountType": ctype,
        "freeShipping": free_shipping,
        "maxDiscount": max_discount,
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
