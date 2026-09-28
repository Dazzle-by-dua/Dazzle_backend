from typing import List
from fastapi import APIRouter, HTTPException, Depends
from app.database import get_database, clean_docs
from app.models.schemas import CustomerOut
from app.security import get_current_admin

router = APIRouter(prefix="/api/customers", tags=["Customers"])

@router.get("", response_model=List[CustomerOut])
async def get_customers(admin: dict = Depends(get_current_admin)):
    db = get_database()
    orders = await db.orders.find({}).sort("created_at", -1).to_list(length=1000)

    cust_map = {}
    for r in orders:
        email = (r.get("email") or "anonymous@example.com").strip().lower()
        if email not in cust_map:
            cust_map[email] = {
                "email": r.get("email", ""),
                "customer": r.get("customer", "Customer"),
                "phone": r.get("phone", ""),
                "address": r.get("address", ""),
                "totalOrders": 0,
                "totalSpent": 0.0,
                "lastOrderDate": r.get("date", "")
            }
        cust_map[email]["totalOrders"] += 1
        if r.get("status") != "Cancelled":
            cust_map[email]["totalSpent"] += float(r.get("total") or 0)

    return list(cust_map.values())

@router.get("/{email}")
async def get_customer_details(email: str, admin: dict = Depends(get_current_admin)):
    db = get_database()
    orders = await db.orders.find({"email": {"$regex": f"^{email}$", "$options": "i"}}).sort("created_at", -1).to_list(length=1000)
    if not orders:
        raise HTTPException(status_code=404, detail="Customer not found.")

    total_spent = sum(float(o.get("total") or 0) for o in orders if o.get("status") != "Cancelled")
    first = orders[0]

    return {
        "customer": {
            "name": first.get("customer"),
            "email": first.get("email"),
            "phone": first.get("phone"),
            "address": first.get("address"),
            "totalOrders": len(orders),
            "totalSpent": total_spent,
            "lastOrderDate": first.get("date")
        },
        "orders": clean_docs(orders)
    }
