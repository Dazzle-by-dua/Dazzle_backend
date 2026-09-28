import random
import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from app.database import get_database, clean_doc, clean_docs
from app.models.schemas import OrderOut, OrderCreate, OrderStatusUpdate
from app.security import get_current_admin

router = APIRouter(prefix="/api/orders", tags=["Orders"])

@router.get("", response_model=List[OrderOut])
async def get_orders(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    db = get_database()
    query = {}

    if status and status.lower() != "all":
        query["status"] = {"$regex": f"^{status}$", "$options": "i"}

    if search:
        regex_term = {"$regex": search, "$options": "i"}
        query["$or"] = [{"id": regex_term}, {"customer": regex_term}, {"email": regex_term}, {"phone": regex_term}]

    items = await db.orders.find(query).sort("created_at", -1).to_list(length=1000)
    return clean_docs(items)

@router.get("/{order_id}", response_model=OrderOut)
async def get_order_by_id(order_id: str):
    db = get_database()
    order = await db.orders.find_one({"id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    return clean_doc(order)

@router.post("", response_model=OrderOut, status_code=201)
async def create_order(payload: OrderCreate):
    db = get_database()
    now = datetime.datetime.now()
    now_iso = now.isoformat()
    formatted_date = payload.date or now.strftime("%d %b %Y")

    order_id = payload.id
    if not order_id:
        rand_num = random.randint(100, 999)
        order_id = f"DBD-{now.year}-{rand_num}"

    items_dict_list = [item.model_dump() for item in payload.items]

    doc = {
        "id": order_id,
        "customer": payload.customer,
        "email": payload.email,
        "phone": payload.phone or "",
        "date": formatted_date,
        "total": float(payload.total),
        "status": payload.status or "Processing",
        "paymentMethod": payload.paymentMethod or "Cash on Delivery",
        "address": payload.address or "",
        "items": items_dict_list,
        "created_at": now_iso,
        "updated_at": now_iso
    }
    await db.orders.insert_one(doc)
    return clean_doc(doc)

@router.patch("/{order_id}/status", response_model=OrderOut)
async def update_order_status(order_id: str, payload: OrderStatusUpdate, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.orders.find_one({"id": order_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found.")

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"status": payload.status, "updated_at": now_iso}}
    )
    updated = await db.orders.find_one({"id": order_id})
    return clean_doc(updated)

@router.delete("/{order_id}")
async def delete_order(order_id: str, admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.orders.find_one({"id": order_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found.")

    await db.orders.delete_one({"id": order_id})
    return {"success": True, "message": f"Order {order_id} deleted."}
