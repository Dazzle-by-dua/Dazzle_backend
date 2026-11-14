"""
Unit and integration tests for Dazzle by Dua coupon system:
- FREEDEL free-delivery coupon (case-insensitivity, whitespace trimming)
- Rejection of invalid/expired coupons
- Parity across Cash on Delivery and Razorpay orders
- Order records saving coupon_code, original_delivery_charge, final_delivery_charge, delivery_discount
- Server-authoritative calculation preventing frontend/developer-tools tampering
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

from app.main import app
from app.database import get_database, init_db
from app.delivery_rules import calculate_delivery_charge

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    """Ensure in-memory mock database is initialized."""
    asyncio.run(init_db())


# =========================================================================
# 1. Coupon Validation Endpoint Tests
# =========================================================================

def test_freedel_validation_case_and_whitespace():
    """FREEDEL coupon works case-insensitively and trims spaces."""
    variations = ["FREEDEL", "freedel", "  FREEDEL  ", "  freedel  ", "FreeDel"]

    for code in variations:
        resp = client.post("/api/offers/coupons/validate", json={
            "code": code,
            "orderTotal": 1000.0,
            "deliveryFee": 50.0,
            "city": "Hyderabad",
            "state": "Telangana"
        })
        assert resp.status_code == 200, f"Failed for code variation: {code}"
        data = resp.json()
        assert data["valid"] is True
        assert data["freeShipping"] is True
        assert data["deliveryDiscount"] == 50.0
        assert data["discountAmount"] == 0.0
        assert "FREEDEL" in data["message"].upper()


def test_freedel_validation_with_city_state_delivery_fee():
    """FREEDEL calculates delivery discount based on provided location if deliveryFee omitted."""
    # Rest of India: 90
    resp = client.post("/api/offers/coupons/validate", json={
        "code": "FREEDEL",
        "orderTotal": 1200.0,
        "city": "Bengaluru",
        "state": "Karnataka"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["deliveryDiscount"] == 90.0

    # Rest of Telangana: 70
    resp_ts = client.post("/api/offers/coupons/validate", json={
        "code": "FREEDEL",
        "orderTotal": 1200.0,
        "city": "Warangal",
        "state": "Telangana"
    })
    assert resp_ts.status_code == 200
    assert resp_ts.json()["deliveryDiscount"] == 70.0


def test_invalid_coupon_validation():
    """Invalid, unknown or fake coupons return valid=False with an informative error message."""
    invalid_codes = ["INVALID10", "FAKECODE", "NOT_A_COUPON", "DISCOUNT99"]

    for code in invalid_codes:
        resp = client.post("/api/offers/coupons/validate", json={
            "code": code,
            "orderTotal": 1000.0,
            "city": "Hyderabad",
            "state": "Telangana"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data["deliveryDiscount"] == 0.0
        assert data["discountAmount"] == 0.0
        assert "Invalid or expired coupon" in data["message"]


def test_coupon_min_order_validation():
    """Coupons with minimum order requirements reject subtotals below minimum."""
    # Seed a coupon with minOrder
    db = get_database()
    asyncio.run(db.coupons.update_one(
        {"code": "VIP500"},
        {"$set": {
            "id": "c_vip500",
            "code": "VIP500",
            "title": "VIP Discount",
            "discount": 500.0,
            "type": "fixed",
            "minOrder": 3000.0,
            "active": True
        }},
        upsert=True
    ))

    resp_fail = client.post("/api/offers/coupons/validate", json={
        "code": "VIP500",
        "orderTotal": 1500.0
    })
    assert resp_fail.status_code == 200
    assert resp_fail.json()["valid"] is False
    assert "at least" in resp_fail.json()["message"]


# =========================================================================
# 2. Cash on Delivery (COD) Checkout with FREEDEL
# =========================================================================

def test_cod_order_creation_with_freedel():
    """
    Placing a COD order with FREEDEL:
    - Product subtotal unchanged
    - Delivery fee becomes 0
    - Total equals subtotal
    - Order document stores original and final delivery charges and discount
    """
    payload = {
        "customer": "Fatima Begum",
        "email": "fatima@example.com",
        "phone": "+91 9876543210",
        "address": "Banjara Hills Road No 10",
        "landmark": "Near GVK Mall",
        "city": "Hyderabad",
        "state": "Telangana",
        "postal_code": "500034",
        "coupon_code": "FREEDEL",
        "total": 9999.0, # Intentional fake client total
        "paymentMethod": "Cash on Delivery",
        "items": [
            {
                "id": 1,
                "name": "Moissanite Solitaire Ring",
                "price": 2499.0, # Client sends tampered price 2499, server uses trusted DB price 4990
                "qty": 1
            }
        ]
    }

    resp = client.post("/api/orders", json=payload)
    assert resp.status_code == 201
    order = resp.json()

    # Subtotal from trusted MongoDB database price (4990.0)
    assert order["subtotal"] == 4990.0
    assert order["coupon_code"] == "FREEDEL"
    assert order["original_delivery_charge"] == 50.0
    assert order["final_delivery_charge"] == 0.0
    assert order["delivery_discount"] == 50.0
    assert order["delivery_fee"] == 0.0
    assert order["shipping_fee"] == 0.0
    # Total must equal subtotal (4990.0 + 0.0 = 4990.0)
    assert order["total"] == 4990.0
    assert order["paymentStatus"] == "Pending"
    assert order["paymentMethod"] == "Cash on Delivery"


def test_cod_order_creation_case_and_whitespace():
    """FREEDEL in lowercase with spaces is accepted and normalized on order creation."""
    payload = {
        "customer": "Ayesha Khan",
        "email": "ayesha@example.com",
        "phone": "+91 9876543211",
        "address": "MG Road",
        "landmark": "Metro Station",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
        "coupon_code": "   freedel   ",
        "total": 0.0,
        "paymentMethod": "Cash on Delivery",
        "items": [
            {
                "id": 1,
                "name": "Moissanite Solitaire Ring",
                "price": 2499.0,
                "qty": 2
            }
        ]
    }

    resp = client.post("/api/orders", json=payload)
    assert resp.status_code == 201
    order = resp.json()

    # Subtotal: 4990 * 2 = 9980
    assert order["subtotal"] == 9980.0
    assert order["coupon_code"] == "FREEDEL"
    assert order["original_delivery_charge"] == 90.0 # Karnataka = 90
    assert order["final_delivery_charge"] == 0.0
    assert order["delivery_discount"] == 90.0
    assert order["total"] == 9980.0


# =========================================================================
# 3. Razorpay Checkout with FREEDEL
# =========================================================================

@patch("app.routers.orders.create_razorpay_order")
def test_razorpay_order_creation_with_freedel(mock_rzp_create):
    """
    Razorpay order creation with FREEDEL:
    - Server verifies coupon
    - Razorpay order amount matches the discounted total in paise
    - MongoDB draft order has coupon_code, original and final delivery charges
    """
    mock_rzp_create.return_value = {
        "razorpay_order_id": "order_mock_freedel_123",
        "key_id": "rzp_test_mock",
        "amount": 499000,  # 4990.00 * 100 paise
        "currency": "INR"
    }

    payload = {
        "customer": "Zainab Ali",
        "email": "zainab@example.com",
        "phone": "+91 9876543212",
        "address": "Banjara Hills",
        "landmark": "Near Taj Krishna",
        "city": "Hyderabad",
        "state": "Telangana",
        "postal_code": "500034",
        "coupon_code": "FREEDEL",
        "items": [
            {
                "id": 1,
                "name": "Moissanite Solitaire Ring",
                "price": 2499.0, # Client attempt at tampering
                "qty": 1
            }
        ]
    }

    resp = client.post("/api/orders/razorpay/create-order", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["success"] is True
    assert data["total"] == 4990.0
    assert data["subtotal"] == 4990.0
    assert data["coupon_code"] == "FREEDEL"
    assert data["original_delivery_charge"] == 50.0
    assert data["final_delivery_charge"] == 0.0
    assert data["delivery_discount"] == 50.0
    assert data["delivery_fee"] == 0.0

    # Ensure amount passed to Razorpay gateway matched discounted total exactly
    mock_rzp_create.assert_called_once_with(
        amount_in_rupees=4990.0,
        receipt=data["order_id"],
        notes={
            "order_id": data["order_id"],
            "customer": "Zainab Ali",
            "email": "zainab@example.com"
        }
    )

    # Verify drafted order in DB
    db = get_database()
    draft_order = asyncio.run(db.orders.find_one({"id": data["order_id"]}))
    assert draft_order is not None
    assert draft_order["coupon_code"] == "FREEDEL"
    assert draft_order["original_delivery_charge"] == 50.0
    assert draft_order["final_delivery_charge"] == 0.0
    assert draft_order["delivery_discount"] == 50.0
    assert draft_order["total"] == 4990.0


# =========================================================================
# 4. Security & Tamper Proofing
# =========================================================================

def test_order_rejection_on_invalid_coupon():
    """Attempting to create an order with an invalid or expired coupon raises HTTP 400."""
    payload = {
        "customer": "Attacker",
        "email": "attacker@example.com",
        "phone": "+91 9999999999",
        "address": "Somewhere",
        "landmark": "Near Landmark",
        "city": "Hyderabad",
        "state": "Telangana",
        "postal_code": "500001",
        "coupon_code": "EXPIRED_OR_FAKE",
        "total": 100.0,
        "items": [
            {
                "id": 1,
                "name": "Moissanite Solitaire Ring",
                "price": 2499.0,
                "qty": 1
            }
        ]
    }

    resp = client.post("/api/orders", json=payload)
    assert resp.status_code == 400
    assert "Invalid or expired coupon" in resp.json()["detail"]


def test_order_rejection_when_subtotal_below_min_order():
    """Attempting to use a coupon when subtotal does not meet minOrder raises HTTP 400."""
    db = get_database()
    asyncio.run(db.coupons.update_one(
        {"code": "BIGORDER"},
        {"$set": {
            "id": "c_bigorder",
            "code": "BIGORDER",
            "title": "Big Order Discount",
            "discount": 500.0,
            "type": "fixed",
            "minOrder": 10000.0,
            "active": True
        }},
        upsert=True
    ))

    payload = {
        "customer": "Test Customer",
        "email": "test@example.com",
        "phone": "+91 9876543210",
        "address": "Banjara Hills",
        "landmark": "Near Mall",
        "city": "Hyderabad",
        "state": "Telangana",
        "postal_code": "500034",
        "coupon_code": "BIGORDER",
        "total": 2499.0,
        "items": [
            {
                "id": 1,
                "name": "Moissanite Solitaire Ring",
                "price": 2499.0,
                "qty": 1
            }
        ]
    }

    resp = client.post("/api/orders", json=payload)
    assert resp.status_code == 400
    assert "must be at least ₹10,000" in resp.json()["detail"]


def test_normal_order_without_coupon_pays_full_delivery():
    """An order without a coupon pays the standard location-based delivery fee."""
    payload = {
        "customer": "Regular Customer",
        "email": "regular@example.com",
        "phone": "+91 9876543210",
        "address": "Banjara Hills",
        "landmark": "Near Mall",
        "city": "Hyderabad",
        "state": "Telangana",
        "postal_code": "500034",
        "coupon_code": None,
        "total": 0.0, # Client attempts 0 total
        "items": [
            {
                "id": 1,
                "name": "Moissanite Solitaire Ring",
                "price": 2499.0,
                "qty": 1
            }
        ]
    }

    resp = client.post("/api/orders", json=payload)
    assert resp.status_code == 201
    order = resp.json()

    assert order["coupon_code"] is None
    assert order["original_delivery_charge"] == 50.0
    assert order["final_delivery_charge"] == 50.0
    assert order["delivery_discount"] == 0.0
    assert order["delivery_fee"] == 50.0
    # Total is 4990 + 50 = 5040
    assert order["total"] == 5040.0


# =========================================================================
# 5. Public Coupons Listing, Max Discount, Expiry & Usage Limit Tests
# =========================================================================

def test_public_coupons_endpoint_returns_only_active():
    """GET /api/offers/coupons/public returns only active, safe coupons and includes FREEDEL."""
    db = get_database()
    asyncio.run(db.coupons.insert_one({
        "id": "c_active_test",
        "code": "TESTACTIVE",
        "title": "Active Promo",
        "discount": 15.0,
        "type": "percent",
        "minOrder": 500.0,
        "active": True
    }))
    asyncio.run(db.coupons.insert_one({
        "id": "c_inactive_test",
        "code": "TESTINACTIVE",
        "title": "Disabled Promo",
        "discount": 50.0,
        "type": "percent",
        "minOrder": 0.0,
        "active": False
    }))

    resp = client.get("/api/offers/coupons/public")
    assert resp.status_code == 200
    coupons = resp.json()
    assert isinstance(coupons, list)

    codes = [c["code"] for c in coupons]
    assert "TESTACTIVE" in codes
    assert "FREEDEL" in codes
    assert "TESTINACTIVE" not in codes


def test_coupon_max_discount_cap_validation_and_order():
    """Ensure maxDiscount caps percent discounts during validation and order creation."""
    db = get_database()
    asyncio.run(db.coupons.update_one(
        {"code": "CAPPED20"},
        {"$set": {
            "id": "c_capped20",
            "code": "CAPPED20",
            "title": "20% off up to 200",
            "discount": 20.0,
            "type": "percent",
            "minOrder": 500.0,
            "maxDiscount": 200.0,
            "active": True
        }},
        upsert=True
    ))

    # Validate with 3000 subtotal (20% would be 600, capped at 200)
    resp = client.post("/api/offers/coupons/validate", json={
        "code": "CAPPED20",
        "orderTotal": 3000.0,
        "city": "Hyderabad",
        "state": "Telangana"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["discountAmount"] == 200.0

    # COD order with CAPPED20
    payload = {
        "customer": "Capped Tester",
        "email": "capped@example.com",
        "phone": "+91 9876543210",
        "address": "Banjara Hills",
        "landmark": "Near Mall",
        "city": "Hyderabad",
        "state": "Telangana",
        "postal_code": "500034",
        "coupon_code": "CAPPED20",
        "total": 4840.0,
        "items": [
            {
                "id": 1,
                "name": "Moissanite Solitaire Ring",
                "price": 2499.0,
                "qty": 1
            }
        ]
    }
    order_resp = client.post("/api/orders", json=payload)
    assert order_resp.status_code == 201
    order_data = order_resp.json()
    # Subtotal 4990, 20% = 998, capped at 200 discount. Delivery = 50. Total = 4990 - 200 + 50 = 4840.
    assert order_data["discount"] == 200.0
    assert order_data["total"] == 4840.0


def test_coupon_expiry_and_future_valid_from():
    """Coupons with past expiry or future validFrom are rejected."""
    db = get_database()
    asyncio.run(db.coupons.update_one(
        {"code": "PASTEXP"},
        {"$set": {
            "id": "c_pastexp",
            "code": "PASTEXP",
            "title": "Expired Promo",
            "discount": 10.0,
            "type": "percent",
            "expiry": "2020-01-01",
            "active": True
        }},
        upsert=True
    ))
    asyncio.run(db.coupons.update_one(
        {"code": "FUTUREFROM"},
        {"$set": {
            "id": "c_futurefrom",
            "code": "FUTUREFROM",
            "title": "Future Promo",
            "discount": 10.0,
            "type": "percent",
            "validFrom": "2030-01-01",
            "active": True
        }},
        upsert=True
    ))

    # Expired
    resp_exp = client.post("/api/offers/coupons/validate", json={
        "code": "PASTEXP",
        "orderTotal": 1000.0
    })
    assert resp_exp.status_code == 200
    assert resp_exp.json()["valid"] is False
    assert "expired" in resp_exp.json()["message"].lower()

    # Future start
    resp_fut = client.post("/api/offers/coupons/validate", json={
        "code": "FUTUREFROM",
        "orderTotal": 1000.0
    })
    assert resp_fut.status_code == 200
    assert resp_fut.json()["valid"] is False
    assert "not active yet" in resp_fut.json()["message"].lower()


def test_coupon_usage_limit_and_increment():
    """Coupons with usageLimit reject after usedCount reaches usageLimit, and COD placement increments usedCount."""
    db = get_database()
    asyncio.run(db.coupons.update_one(
        {"code": "LIMITED1"},
        {"$set": {
            "id": "c_limited1",
            "code": "LIMITED1",
            "title": "One-time code",
            "discount": 100.0,
            "type": "fixed",
            "usageLimit": 1,
            "usedCount": 0,
            "active": True
        }},
        upsert=True
    ))

    # Place COD order with LIMITED1
    payload = {
        "customer": "Limit Tester",
        "email": "limit@example.com",
        "phone": "+91 9876543210",
        "address": "Banjara Hills",
        "city": "Hyderabad",
        "state": "Telangana",
        "postal_code": "500034",
        "coupon_code": "LIMITED1",
        "total": 4940.0,
        "items": [
            {
                "id": 1,
                "name": "Moissanite Solitaire Ring",
                "price": 2499.0,
                "qty": 1
            }
        ]
    }
    resp1 = client.post("/api/orders", json=payload)
    assert resp1.status_code == 201

    # Check coupon usedCount incremented to 1
    updated_c = asyncio.run(db.coupons.find_one({"code": "LIMITED1"}))
    assert updated_c["usedCount"] == 1

    # Trying to use LIMITED1 again should be rejected
    resp2 = client.post("/api/offers/coupons/validate", json={
        "code": "LIMITED1",
        "orderTotal": 1000.0
    })
    assert resp2.status_code == 200
    assert resp2.json()["valid"] is False
    assert "usage limit has been reached" in resp2.json()["message"].lower()

    # Placing second order should be rejected
    resp3 = client.post("/api/orders", json=payload)
    assert resp3.status_code == 400
    assert "usage limit" in resp3.json()["detail"].lower()
