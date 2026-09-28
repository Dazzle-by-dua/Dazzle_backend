import sys
import io
import json
import pytest
from starlette.testclient import TestClient

from app.main import app
from app.database import init_db, reset_all_data

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    reset_all_data()

# 1. Health & Root
def test_root_and_health():
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["brand"] == "Dazzle by Dua"

    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

# 2. Authentication
def test_admin_auth_success_and_failure():
    # Invalid password
    res = client.post("/api/auth/login", json={"username": "admin", "password": "wrongpassword"})
    assert res.status_code == 401

    # Valid login
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "token" in data
    assert data["user"]["user"] == "Dua"

    token = data["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify /api/auth/me
    res_me = client.get("/api/auth/me", headers=headers)
    assert res_me.status_code == 200
    assert res_me.json()["email"] == "admin@dazzlebydua.com"

    # Logout
    res_logout = client.post("/api/auth/logout")
    assert res_logout.status_code == 200

# Helper to get admin headers
def get_auth_headers():
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}

# 3. Products Endpoints
def test_products_crud():
    headers = get_auth_headers()

    # Get initial products
    res = client.get("/api/products")
    assert res.status_code == 200
    products = res.json()
    assert len(products) == 8

    # Filter by category
    res_cat = client.get("/api/products?category=necklaces")
    assert res_cat.status_code == 200
    assert all(p["category"] == "necklaces" for p in res_cat.json())

    # Filter by inStock
    res_stock = client.get("/api/products?inStock=false")
    assert res_stock.status_code == 200
    assert len(res_stock.json()) >= 1

    # Add product
    new_prod_payload = {
        "name": "Emerald Solitaire Pendant",
        "price": 7990,
        "oldPrice": 9990,
        "category": "necklaces",
        "inStock": True,
        "sku": "DBD-NC-009",
        "material": "18K Gold Vermeil & Lab Emerald",
        "description": "Timeless radiant green emerald pendant.",
        "badges": ["new"],
        "variants": ["18K Champagne Gold"],
        "images": ["product_flower_necklace.jpg"]
    }
    res_add = client.post("/api/products", json=new_prod_payload, headers=headers)
    assert res_add.status_code == 201
    new_prod = res_add.json()
    new_id = new_prod["id"]
    assert new_prod["name"] == "Emerald Solitaire Pendant"

    # Toggle stock
    res_toggle = client.patch(f"/api/products/{new_id}/stock", json={"inStock": False}, headers=headers)
    assert res_toggle.status_code == 200
    assert res_toggle.json()["inStock"] is False

    # Update product
    res_update = client.put(f"/api/products/{new_id}", json={"price": 8490}, headers=headers)
    assert res_update.status_code == 200
    assert res_update.json()["price"] == 8490

    # Get details map
    res_details = client.get("/api/products/details/map")
    assert res_details.status_code == 200
    assert str(new_id) in res_details.json()

    # Delete product
    res_del = client.delete(f"/api/products/{new_id}", headers=headers)
    assert res_del.status_code == 200

# 4. Categories Endpoints
def test_categories_crud():
    headers = get_auth_headers()

    res = client.get("/api/categories")
    assert res.status_code == 200
    assert len(res.json()) >= 4

    # Add category
    new_cat = {
        "id": "anklets",
        "name": "Anklets",
        "desc": "Dainty handcrafted anklets",
        "img": "product_bracelet.jpg"
    }
    res_add = client.post("/api/categories", json=new_cat, headers=headers)
    assert res_add.status_code == 201
    assert res_add.json()["name"] == "Anklets"

    # Update category
    res_up = client.put("/api/categories/anklets", json={"name": "Fine Anklets"}, headers=headers)
    assert res_up.status_code == 200
    assert res_up.json()["name"] == "Fine Anklets"

    # Delete category
    res_del = client.delete("/api/categories/anklets", headers=headers)
    assert res_del.status_code == 200

# 5. Orders Endpoints
def test_orders_flow():
    headers = get_auth_headers()

    # Place order (storefront)
    order_data = {
        "customer": "Rania Al-Noor",
        "email": "rania@example.com",
        "phone": "+91 99887 76655",
        "address": "404 Sky Towers, Worli, Mumbai",
        "total": 4990,
        "paymentMethod": "UPI",
        "items": [
            {"id": 1, "name": "Flower Pendant Necklace", "price": 4990, "qty": 1, "variant": "18K Gold"}
        ]
    }
    res_order = client.post("/api/orders", json=order_data)
    assert res_order.status_code == 201
    created_order = res_order.json()
    order_id = created_order["id"]
    assert created_order["status"] == "Processing"

    # Update status (admin)
    res_stat = client.patch(f"/api/orders/{order_id}/status", json={"status": "Shipped"}, headers=headers)
    assert res_stat.status_code == 200
    assert res_stat.json()["status"] == "Shipped"

    # Customer analytics should now have rania
    res_cust = client.get("/api/customers", headers=headers)
    assert res_cust.status_code == 200
    assert any(c["email"].lower() == "rania@example.com" for c in res_cust.json())

# 6. Reviews Endpoints
def test_reviews_flow():
    headers = get_auth_headers()

    # Submit review (storefront)
    rev_payload = {
        "name": "Kavita S.",
        "rating": 5,
        "text": "Stunning piece of jewellery, highly recommended!",
        "product": "Flower Pendant Necklace"
    }
    res_rev = client.post("/api/reviews", json=rev_payload)
    assert res_rev.status_code == 201
    rev_id = res_rev.json()["id"]

    # Approve/hide review (admin)
    res_hide = client.patch(f"/api/reviews/{rev_id}/status", json={"approved": False}, headers=headers)
    assert res_hide.status_code == 200
    assert res_hide.json()["approved"] is False

    # Storefront query approved only
    res_approved = client.get("/api/reviews?approved_only=true")
    assert res_approved.status_code == 200
    assert all(r["approved"] is True for r in res_approved.json())

# 7. Offers & Coupons Validation
def test_offers_and_coupon_validation():
    headers = get_auth_headers()

    # Validate coupon DAZZLE10 with order total 5000 (10% off -> 500)
    res_val = client.post("/api/offers/coupons/validate", json={"code": "DAZZLE10", "orderTotal": 5000})
    assert res_val.status_code == 200
    data = res_val.json()
    assert data["valid"] is True
    assert data["discountAmount"] == 500.0

    # Validate with order below minimum (DAZZLE10 requires 1500)
    res_low = client.post("/api/offers/coupons/validate", json={"code": "DAZZLE10", "orderTotal": 500})
    assert res_low.status_code == 200
    assert res_low.json()["valid"] is False

    # Validate non-existing code
    res_none = client.post("/api/offers/coupons/validate", json={"code": "FAKECODE", "orderTotal": 5000})
    assert res_none.status_code == 200
    assert res_none.json()["valid"] is False

# 8. Homepage, Settings, Navigation, Pages
def test_cms_configurations():
    headers = get_auth_headers()

    # Homepage
    res_hp = client.get("/api/homepage")
    assert res_hp.status_code == 200
    assert "hero" in res_hp.json()
    assert "announcement" in res_hp.json()

    # Update section
    res_up_hp = client.patch("/api/homepage/announcement", json={"text": "Exclusive Diwali Sale Live Now!"}, headers=headers)
    assert res_up_hp.status_code == 200
    assert res_up_hp.json()["announcement"]["text"] == "Exclusive Diwali Sale Live Now!"

    # Settings
    res_set = client.get("/api/settings")
    assert res_set.status_code == 200
    assert res_set.json()["siteName"] == "Dazzle by Dua"

    # Navigation
    res_nav = client.get("/api/navigation")
    assert res_nav.status_code == 200
    assert len(res_nav.json()["header"]) >= 6

    # Pages
    res_pages = client.get("/api/pages")
    assert res_pages.status_code == 200
    assert "care_guide" in res_pages.json()

# 9. Dashboard Stats
def test_dashboard_stats():
    headers = get_auth_headers()
    res = client.get("/api/dashboard/stats", headers=headers)
    assert res.status_code == 200
    stats = res.json()
    assert stats["totalProducts"] >= 8
    assert stats["totalOrders"] >= 3
    assert stats["totalRevenue"] > 0
    assert len(stats["recentOrders"]) >= 1

# 10. Backup Export, Reset & Import
def test_backup_and_restore():
    headers = get_auth_headers()

    # Export
    res_exp = client.get("/api/backup/export", headers=headers)
    assert res_exp.status_code == 200
    backup_data = res_exp.json()

    # Verify all 8 frontend keys exist
    expected_keys = ["products", "categories", "reviews", "offers", "homepage", "orders", "settings", "navigation"]
    for k in expected_keys:
        assert k in backup_data

    # Modify one product and import
    backup_data["products"][0]["name"] = "Imported Royal Pearl Necklace"
    res_imp = client.post("/api/backup/import", json=backup_data, headers=headers)
    assert res_imp.status_code == 200

    # Verify product updated
    res_prods = client.get("/api/products")
    assert any(p["name"] == "Imported Royal Pearl Necklace" for p in res_prods.json())

    # Reset
    res_reset = client.post("/api/backup/reset", headers=headers)
    assert res_reset.status_code == 200
