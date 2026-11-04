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
