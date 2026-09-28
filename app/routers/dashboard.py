import json
from fastapi import APIRouter, Depends
from app.database import get_db
from app.models.schemas import DashboardStatsOut
from app.security import get_current_admin

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard Statistics"])

@router.get("/stats", response_model=DashboardStatsOut)
def get_dashboard_stats(admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()

        # Orders stats & revenue
        cursor.execute("SELECT total, status FROM orders;")
        all_orders = cursor.fetchall()
        total_orders = len(all_orders)
        total_revenue = sum(float(o["total"] or 0) for o in all_orders if o["status"] != "Cancelled")

        # Products stats
        cursor.execute("SELECT COUNT(*) FROM products;")
        total_products = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM products WHERE inStock = 0;")
        out_of_stock_count = cursor.fetchone()[0]

        cursor.execute("SELECT * FROM products WHERE inStock = 0 LIMIT 10;")
        low_stock_rows = cursor.fetchall()
        low_stock_prods = []
        for r in low_stock_rows:
            low_stock_prods.append({
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
            })

        # Recent 5 orders
        cursor.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 5;")
        recent_order_rows = cursor.fetchall()
        recent_orders = []
        for r in recent_order_rows:
            recent_orders.append({
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

        # Reviews stats
        cursor.execute("SELECT COUNT(*) FROM reviews;")
        total_reviews = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM reviews WHERE approved = 0;")
        pending_reviews = cursor.fetchone()[0]

        cursor.execute("SELECT AVG(rating) FROM reviews;")
        avg_rating_val = cursor.fetchone()[0]
        avg_rating = round(avg_rating_val, 1) if avg_rating_val else 5.0

        cursor.execute("SELECT * FROM reviews ORDER BY id DESC LIMIT 5;")
        recent_review_rows = cursor.fetchall()
        recent_reviews = []
        for r in recent_review_rows:
            recent_reviews.append({
                "id": r["id"],
                "name": r["name"],
                "rating": r["rating"],
                "text": r["text"],
                "date": r["date"],
                "verified": bool(r["verified"]),
                "approved": bool(r["approved"]),
                "product": r["product"]
            })

        # Customers count (unique emails)
        cursor.execute("SELECT COUNT(DISTINCT LOWER(email)) FROM orders;")
        total_customers = cursor.fetchone()[0]

        return {
            "totalRevenue": total_revenue,
            "totalOrders": total_orders,
            "totalProducts": total_products,
            "outOfStockCount": out_of_stock_count,
            "totalReviews": total_reviews,
            "pendingReviews": pending_reviews,
            "avgRating": avg_rating,
            "totalCustomers": total_customers,
            "recentOrders": recent_orders,
            "lowStockProducts": low_stock_prods,
            "recentReviews": recent_reviews
        }
