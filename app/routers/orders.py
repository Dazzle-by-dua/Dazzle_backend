import json
import random
import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from app.database import get_db
from app.models.schemas import OrderOut, OrderCreate, OrderStatusUpdate
from app.security import get_current_admin

router = APIRouter(prefix="/api/orders", tags=["Orders"])

def _row_to_order(r) -> dict:
    return {
        "id": r["id"],
        "customer": r["customer"],
        "email": r["email"],
        "phone": r["phone"],
        "date": r["date"],
        "total": r["total"],
        "status": r["status"],
        "paymentMethod": r["paymentMethod"],
        "address": r["address"],
        "items": json.loads(r["items"]) if r["items"] else []
    }

@router.get("", response_model=List[OrderOut])
def get_orders(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    query = "SELECT * FROM orders WHERE 1=1"
    params = []

    if status and status.lower() != "all":
        query += " AND LOWER(status) = ?"
        params.append(status.lower())

    if search:
        query += " AND (LOWER(id) LIKE ? OR LOWER(customer) LIKE ? OR LOWER(email) LIKE ? OR LOWER(phone) LIKE ?)"
        term = f"%{search.lower()}%"
        params.extend([term, term, term, term])

    query += " ORDER BY created_at DESC"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [_row_to_order(r) for r in rows]

@router.get("/{order_id}", response_model=OrderOut)
def get_order_by_id(order_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found.")
        return _row_to_order(row)

@router.post("", response_model=OrderOut, status_code=201)
def create_order(payload: OrderCreate):
    now = datetime.datetime.now()
    now_iso = now.isoformat()
    formatted_date = payload.date or now.strftime("%d %b %Y")

    order_id = payload.id
    if not order_id:
        rand_num = random.randint(100, 999)
        order_id = f"DBD-{now.year}-{rand_num}"

    items_dict_list = [item.model_dump() for item in payload.items]

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO orders (id, customer, email, phone, date, total, status, paymentMethod, address, items, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order_id,
                payload.customer,
                payload.email,
                payload.phone or "",
                formatted_date,
                payload.total,
                payload.status or "Processing",
                payload.paymentMethod or "Cash on Delivery",
                payload.address or "",
                json.dumps(items_dict_list),
                now_iso,
                now_iso
            )
        )
        cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = cursor.fetchone()

    return _row_to_order(row)

@router.patch("/{order_id}/status", response_model=OrderOut)
def update_order_status(order_id: str, payload: OrderStatusUpdate, admin: dict = Depends(get_current_admin)):
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Order not found.")

        cursor.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (payload.status, now_iso, order_id)
        )
        cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = cursor.fetchone()

    return _row_to_order(row)

@router.delete("/{order_id}")
def delete_order(order_id: str, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Order not found.")

        cursor.execute("DELETE FROM orders WHERE id = ?", (order_id,))

    return {"success": True, "message": f"Order {order_id} deleted."}
