from fastapi import APIRouter, Depends
from app.database import get_database, clean_docs
from app.models.schemas import DashboardStatsOut
from app.security import get_current_admin

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard Statistics"])

@router.get("/stats", response_model=DashboardStatsOut)
async def get_dashboard_stats(admin: dict = Depends(get_current_admin)):
    db = get_database()

    # Orders
    all_orders = await db.orders.find({}).to_list(length=5000)
    total_orders = len(all_orders)
    total_revenue = sum(float(o.get("total") or 0) for o in all_orders if o.get("status") != "Cancelled")
    recent_orders = clean_docs(await db.orders.find({}).sort("created_at", -1).limit(5).to_list(5))

    # Products
    total_products = await db.products.count_documents({})
    out_of_stock_count = await db.products.count_documents({"inStock": False})
    low_stock_prods = clean_docs(await db.products.find({"inStock": False}).limit(10).to_list(10))

    # Reviews
    total_reviews = await db.reviews.count_documents({})
    pending_reviews = await db.reviews.count_documents({"approved": False})

    rev_docs = await db.reviews.find({}).to_list(length=1000)
    if rev_docs:
        avg_rating = round(sum(r.get("rating", 5) for r in rev_docs) / len(rev_docs), 1)
    else:
        avg_rating = 5.0

    recent_reviews = clean_docs(await db.reviews.find({}).sort("id", -1).limit(5).to_list(5))

    # Unique customers
    unique_emails = set((o.get("email") or "").strip().lower() for o in all_orders if o.get("email"))
    total_customers = len(unique_emails)

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
