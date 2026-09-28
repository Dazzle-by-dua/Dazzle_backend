import json
from typing import List
from fastapi import APIRouter, HTTPException, Depends
from app.database import get_db
from app.models.schemas import CustomerOut, OrderOut
from app.security import get_current_admin

router = APIRouter(prefix="/api/customers", tags=["Customers"])

@router.get("", response_model=List[CustomerOut])
def get_customers(admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders ORDER BY created_at DESC;")
        rows = cursor.fetchall()

    cust_map = {}
    for r in rows:
        email = (r["email"] or "anonymous@example.com").strip().lower()
        if email not in cust_map:
            cust_map[email] = {
                "email": r["email"],
                "customer": r["customer"],
                "phone": r["phone"],
                "address": r["address"],
                "totalOrders": 0,
                "totalSpent": 0.0,
                "lastOrderDate": r["date"]
            }
        cust_map[email]["totalOrders"] += 1
        if r["status"] != "Cancelled":
            cust_map[email]["totalSpent"] += float(r["total"] or 0)

    return list(cust_map.values())

@router.get("/{email}")
def get_customer_details(email: str, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders WHERE LOWER(email) = ? ORDER BY created_at DESC;", (email.lower(),))
        rows = cursor.fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="Customer not found.")

        orders = []
        total_spent = 0.0
        for r in rows:
            orders.append({
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
            })
            if r["status"] != "Cancelled":
                total_spent += float(r["total"] or 0)

        first = rows[0]
        return {
            "customer": {
                "name": first["customer"],
                "email": first["email"],
                "phone": first["phone"],
                "address": first["address"],
                "totalOrders": len(orders),
                "totalSpent": total_spent,
                "lastOrderDate": first["date"]
            },
            "orders": orders
        }
