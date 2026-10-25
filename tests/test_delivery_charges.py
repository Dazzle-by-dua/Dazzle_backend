"""
Comprehensive unit and integration tests for location-based fixed delivery charges:
- Hyderabad: ₹50
- Rest of Telangana (excluding Hyderabad): ₹70
- All other Indian states and union territories: ₹90
- Casing & whitespace normalization
- Missing / invalid / ambiguous address rejection
- Server-authoritative calculation ignoring client tampering
- Exact parity between Cash on Delivery and Razorpay orders
"""

import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

from app.main import app
from app.database import get_database, init_db
from app.delivery_rules import calculate_delivery_charge

client = TestClient(app)

@pytest.fixture(autouse=True)
def ensure_db_initialized():
    """Ensure in-memory mock database is connected for tests."""
    import asyncio
    asyncio.run(init_db())


# =========================================================================
# 1. Unit Tests: Location Calculation Rules
# =========================================================================

def test_hyderabad_fixed_rate_50():
    res = calculate_delivery_charge(city="Hyderabad", state="Telangana")
    assert res["delivery_fee"] == 50.0
    assert res["rate_type"] == "hyderabad"
    assert res["state"] == "Telangana"

    # Twin city Secunderabad
    res_sec = calculate_delivery_charge(city="Secunderabad", state="Telangana")
    assert res_sec["delivery_fee"] == 50.0
    assert res_sec["rate_type"] == "hyderabad"

    # Cyberabad
    res_cyb = calculate_delivery_charge(city="Cyberabad", state="Telangana")
    assert res_cyb["delivery_fee"] == 50.0
    assert res_cyb["rate_type"] == "hyderabad"

    # State omitted when city is Hyderabad
    res_omit_state = calculate_delivery_charge(city="Hyderabad", state=None)
    assert res_omit_state["delivery_fee"] == 50.0
    assert res_omit_state["rate_type"] == "hyderabad"


def test_rest_of_telangana_fixed_rate_70():
    # Warangal
    res_wgl = calculate_delivery_charge(city="Warangal", state="Telangana")
    assert res_wgl["delivery_fee"] == 70.0
    assert res_wgl["rate_type"] == "telangana"
    assert res_wgl["city"] == "Warangal"

    # Karimnagar
    res_knr = calculate_delivery_charge(city="Karimnagar", state="Telangana")
    assert res_knr["delivery_fee"] == 70.0
    assert res_knr["rate_type"] == "telangana"

    # Nizamabad
    res_nzb = calculate_delivery_charge(city="Nizamabad", state="Telangana")
    assert res_nzb["delivery_fee"] == 70.0
    assert res_nzb["rate_type"] == "telangana"

    # Khammam
    res_kmm = calculate_delivery_charge(city="Khammam", state="Telangana")
    assert res_kmm["delivery_fee"] == 70.0
    assert res_kmm["rate_type"] == "telangana"


def test_other_indian_states_and_uts_fixed_rate_90():
    # Karnataka (Bangalore)
    res_blr = calculate_delivery_charge(city="Bangalore", state="Karnataka")
    assert res_blr["delivery_fee"] == 90.0
    assert res_blr["rate_type"] == "rest_of_india"
    assert res_blr["state"] == "Karnataka"

    # Maharashtra (Mumbai)
    res_mum = calculate_delivery_charge(city="Mumbai", state="Maharashtra")
    assert res_mum["delivery_fee"] == 90.0
    assert res_mum["rate_type"] == "rest_of_india"

    # Delhi (UT)
    res_del = calculate_delivery_charge(city="New Delhi", state="Delhi")
    assert res_del["delivery_fee"] == 90.0
    assert res_del["rate_type"] == "rest_of_india"

    # Tamil Nadu (Chennai)
    res_chn = calculate_delivery_charge(city="Chennai", state="Tamil Nadu")
    assert res_chn["delivery_fee"] == 90.0
    assert res_chn["rate_type"] == "rest_of_india"

    # West Bengal (Kolkata)
    res_kol = calculate_delivery_charge(city="Kolkata", state="West Bengal")
    assert res_kol["delivery_fee"] == 90.0
    assert res_kol["rate_type"] == "rest_of_india"

    # Rajasthan (Jaipur)
    res_jpr = calculate_delivery_charge(city="Jaipur", state="Rajasthan")
    assert res_jpr["delivery_fee"] == 90.0

    # Chandigarh (UT)
    res_chd = calculate_delivery_charge(city="Chandigarh", state="Chandigarh")
    assert res_chd["delivery_fee"] == 90.0

    # Jammu and Kashmir (UT)
    res_jk = calculate_delivery_charge(city="Srinagar", state="Jammu & Kashmir")
    assert res_jk["delivery_fee"] == 90.0


def test_whitespace_and_capitalization_normalization():
    # Mixed casing & leading/trailing whitespace
    res_hyd = calculate_delivery_charge(city="   hYdErAbAd   ", state="  TELANGANA   ")
    assert res_hyd["delivery_fee"] == 50.0

    res_wgl = calculate_delivery_charge(city="   wArAnGaL  ", state="   tElAnGaNa   ")
    assert res_wgl["delivery_fee"] == 70.0

    res_blr = calculate_delivery_charge(city="  bEnGaLuRu  ", state="  kArNaTaKa  ")
    assert res_blr["delivery_fee"] == 90.0


def test_rejection_of_missing_and_ambiguous_locations():
    # Completely missing city and state
    with pytest.raises(Exception) as exc1:
        calculate_delivery_charge(city=None, state=None, address=None)
    assert exc1.value.status_code == 400
    assert "valid Indian state and city" in exc1.value.detail

    # Empty strings
    with pytest.raises(Exception) as exc2:
        calculate_delivery_charge(city="   ", state="   ", address="123 Road")
    assert exc2.value.status_code == 400

    # State is Telangana, but city is missing (cannot determine ₹50 vs ₹70)
    with pytest.raises(Exception) as exc3:
        calculate_delivery_charge(city=None, state="Telangana", address="Near Gandhi Hospital")
    assert exc3.value.status_code == 400
    assert "City name is required" in exc3.value.detail

    # Invalid non-Indian state
    with pytest.raises(Exception) as exc4:
        calculate_delivery_charge(city="Los Angeles", state="California")
    assert exc4.value.status_code == 400
    assert "not a recognized Indian state" in exc4.value.detail

    # International address
    with pytest.raises(Exception) as exc5:
        calculate_delivery_charge(city="Dubai", state="UAE", address="Downtown, Dubai, UAE")
    assert exc5.value.status_code == 400
    assert "only deliver within India" in exc5.value.detail


def test_fallback_address_string_extraction():
    # City and State omitted as separate args, parsed from address
    res_hyd = calculate_delivery_charge(address="Flat 202, Fortune Towers, Banjara Hills, Hyderabad - 500034")
    assert res_hyd["delivery_fee"] == 50.0
    assert res_hyd["rate_type"] == "hyderabad"

    res_wgl = calculate_delivery_charge(address="Hanamkonda, Warangal, Telangana - 506001")
    assert res_wgl["delivery_fee"] == 70.0
    assert res_wgl["rate_type"] == "telangana"

    res_mum = calculate_delivery_charge(address="404 Sky Towers, Worli, Mumbai - 400018")
    assert res_mum["delivery_fee"] == 90.0
    assert res_mum["rate_type"] == "rest_of_india"


# =========================================================================
# 2. HTTP Endpoint: POST /api/orders/delivery-charge
# =========================================================================

def test_public_delivery_charge_api_endpoint():
    # Hyderabad
    res_hyd = client.post("/api/orders/delivery-charge", json={"city": "Hyderabad", "state": "Telangana"})
    assert res_hyd.status_code == 200
    data_hyd = res_hyd.json()
    assert data_hyd["delivery_fee"] == 50.0
    assert data_hyd["rate_type"] == "hyderabad"

    # Warangal
    res_wgl = client.post("/api/orders/delivery-charge", json={"city": "Warangal", "state": "Telangana"})
    assert res_wgl.status_code == 200
    assert res_wgl.json()["delivery_fee"] == 70.0

    # Bangalore
    res_blr = client.post("/api/orders/delivery-charge", json={"city": "Bangalore", "state": "Karnataka"})
    assert res_blr.status_code == 200
    assert res_blr.json()["delivery_fee"] == 90.0

    # Invalid state
    res_err = client.post("/api/orders/delivery-charge", json={"city": "Seattle", "state": "Washington"})
    assert res_err.status_code == 400
    assert "not a recognized Indian state" in res_err.json()["detail"]


# =========================================================================
# 3. Order Integration: Server Calculates Fee & Ignores Client Manipulation
# =========================================================================

def test_cod_order_creation_enforces_location_delivery_fee_ignoring_tampering():
    # Item 1 true price = 4990 in DB
    # Client tries to send fake delivery_fee 0.0 and fake total 100.0 for Hyderabad
    payload_hyd = {
        "id": "DBD-COD-HYD-01",
        "customer": "Zainab Begum",
        "email": "zainab@example.com",
        "city": "Hyderabad",
        "state": "Telangana",
        "address": "Banjara Hills, Hyderabad, Telangana",
        "landmark": "Near GVK Mall",
        "total": 100.0,          # Client attempted price tampering
        "delivery_fee": 0.0,     # Client attempted free delivery tampering
        "paymentMethod": "Cash on Delivery",
        "paymentStatus": "Pending",
        "items": [{"id": 1, "name": "Necklace", "price": 4990.0, "qty": 1}]
    }

    res = client.post("/api/orders", json=payload_hyd)
    assert res.status_code == 201
    order_data = res.json()

    # Authoritative calculation: Subtotal 4990.0 + Hyderabad delivery 50.0 = 5040.0
    assert order_data["delivery_fee"] == 50.0
    assert order_data["shipping_fee"] == 50.0
    assert order_data["total"] == 5040.0
    assert order_data["subtotal"] == 4990.0
    assert order_data["city"] == "Hyderabad"
    assert order_data["state"] == "Telangana"
    assert order_data["delivery_location_type"] == "hyderabad"


def test_cod_order_creation_telangana_other_city_70():
    payload_wgl = {
        "id": "DBD-COD-WGL-01",
        "customer": "Kiran Kumar",
        "email": "kiran@example.com",
        "city": "Warangal",
        "state": "Telangana",
        "address": "Kakatiya Colony, Warangal, Telangana",
        "landmark": "Opposite Bus Stand",
        "total": 4990.0,
        "paymentMethod": "Cash on Delivery",
        "items": [{"id": 1, "price": 4990.0, "qty": 1}]
    }

    res = client.post("/api/orders", json=payload_wgl)
    assert res.status_code == 201
    order_data = res.json()

    # Subtotal 4990.0 + Rest of Telangana delivery 70.0 = 5060.0
    assert order_data["delivery_fee"] == 70.0
    assert order_data["total"] == 5060.0
    assert order_data["delivery_location_type"] == "telangana"


def test_cod_order_creation_other_indian_state_90():
    payload_mum = {
        "id": "DBD-COD-MUM-01",
        "customer": "Sanjay Rao",
        "email": "sanjay@example.com",
        "city": "Mumbai",
        "state": "Maharashtra",
        "address": "Andheri West, Mumbai, Maharashtra",
        "landmark": "Near Metro Station",
        "total": 4990.0,
        "paymentMethod": "Cash on Delivery",
        "items": [{"id": 1, "price": 4990.0, "qty": 1}]
    }

    res = client.post("/api/orders", json=payload_mum)
    assert res.status_code == 201
    order_data = res.json()

    # Subtotal 4990.0 + Maharashtra delivery 90.0 = 5080.0
    assert order_data["delivery_fee"] == 90.0
    assert order_data["total"] == 5080.0
    assert order_data["delivery_location_type"] == "rest_of_india"


def test_razorpay_and_cod_have_matching_delivery_charges():
    """Verify that both payment rails (Razorpay Online and COD) compute the identical delivery fee and total."""
    rzp_payload = {
        "items": [{"id": 1, "qty": 1}],
        "customer": "Sameer Khan",
        "email": "sameer@example.com",
        "city": "Hyderabad",
        "state": "Telangana",
        "address": "Mehdipatnam, Hyderabad, Telangana",
        "delivery_fee": 0.0  # Ignored by backend
    }

    mock_rzp = {"id": "order_match_test", "amount": 504000, "currency": "INR", "receipt": "DBD-M", "status": "created"}
    with patch("app.razorpay_service.is_razorpay_configured", return_value=True), \
         patch("app.razorpay_service.get_razorpay_client") as mock_client:
        mock_client.return_value.order.create.return_value = mock_rzp

        res_rzp = client.post("/api/orders/razorpay/create-order", json=rzp_payload)
        assert res_rzp.status_code == 200
        rzp_data = res_rzp.json()

        # COD with identical items and location
        cod_payload = {
            "id": "DBD-COD-MATCH",
            "customer": "Sameer Khan",
            "email": "sameer@example.com",
            "city": "Hyderabad",
            "state": "Telangana",
            "address": "Mehdipatnam, Hyderabad, Telangana",
            "total": 100.0, # Client attempt to send tampered total
            "items": [{"id": 1, "qty": 1}]
        }
        res_cod = client.post("/api/orders", json=cod_payload)
        assert res_cod.status_code == 201
        cod_data = res_cod.json()

        # Both rails must produce identical trusted delivery fee and grand total
        assert rzp_data["delivery_fee"] == cod_data["delivery_fee"] == 50.0
        assert rzp_data["total"] == cod_data["total"] == 5040.0
        assert rzp_data["amount"] == int(cod_data["total"] * 100)  # Paise conversion match
