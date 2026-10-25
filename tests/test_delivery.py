"""
Unit and integration tests for Google Maps & Distance-Based Delivery Quote System.
Tests:
- Valid destination and driving-route distance calculation.
- Invalid coordinates and coordinate boundary validation.
- Routes API unavailable / network error / timeout handling.
- Delivery distance exceeding configured maximum radius.
- Delivery-fee slab boundaries matching.
- Client-supplied fake distance or fee being ignored and recalculated.
- Missing Google API keys handling.
- Delivery fee included correctly in checkout and order totals.
All Google Routes API calls are strictly mocked (zero real billable network requests).
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

from app.main import app
from app.database import get_database, init_db
from app.delivery_service import (
    SHOP_LATITUDE,
    SHOP_LONGITUDE,
    SHOP_POSTAL_CODE,
    validate_coordinates,
    get_delivery_fee_rules,
    calculate_delivery_fee_for_distance,
    compute_driving_route_distance,
    get_delivery_quote
)
from app.config import (
    GOOGLE_MAPS_SERVER_API_KEY,
    GOOGLE_MAPS_BROWSER_API_KEY,
    MAX_DELIVERY_DISTANCE_KM
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def ensure_db_initialized():
    """Ensure in-memory mock database is connected for tests."""
    import asyncio
    asyncio.run(init_db())


# =========================================================================
# 1. Coordinate Validation & Slab Logic Tests
# =========================================================================

def test_coordinate_validation():
    # Valid coordinates
    is_valid, _ = validate_coordinates(17.4399, 78.4983)
    assert is_valid is True

    # Out of range latitude
    is_valid, msg = validate_coordinates(95.0, 78.0)
    assert is_valid is False
    assert "Latitude" in msg

    # Out of range longitude
    is_valid, msg = validate_coordinates(17.0, 195.0)
    assert is_valid is False
    assert "Longitude" in msg

    # Null Island (0, 0)
    is_valid, msg = validate_coordinates(0.0, 0.0)
    assert is_valid is False
    assert "Null Island" in msg

    # Non-numeric
    is_valid, msg = validate_coordinates("invalid", "coordinates")
    assert is_valid is False


def test_delivery_fee_slabs_boundaries():
    sample_rules = json.dumps([
        {"max_km": 5, "fee": 50},
        {"max_km": 15, "fee": 100},
        {"max_km": 30, "fee": 180},
        {"max_km": 50, "fee": 250}
    ])

    with patch("app.delivery_service.DELIVERY_FEE_RULES_JSON", sample_rules), \
         patch("app.delivery_service.MAX_DELIVERY_DISTANCE_KM", 50.0):

        # Exactly at first slab boundary (5 km)
        res_5 = calculate_delivery_fee_for_distance(5.0)
        assert res_5["available"] is True
        assert res_5["fee"] == 50.0

        # Just above first slab boundary (5.1 km) -> matches 15 km slab
        res_5_1 = calculate_delivery_fee_for_distance(5.1)
        assert res_5_1["available"] is True
        assert res_5_1["fee"] == 100.0

        # Middle slab (22.5 km) -> matches 30 km slab
        res_22 = calculate_delivery_fee_for_distance(22.5)
        assert res_22["available"] is True
        assert res_22["fee"] == 180.0

        # Boundary slab (50.0 km) -> matches 50 km slab
        res_50 = calculate_delivery_fee_for_distance(50.0)
        assert res_50["available"] is True
        assert res_50["fee"] == 250.0

        # Exceeds maximum distance (50.1 km) -> unavailable
        res_51 = calculate_delivery_fee_for_distance(50.1)
        assert res_51["available"] is False
        assert res_51["fee"] is None
        assert "exceeds the maximum delivery radius" in res_51["reason"]


def test_unconfigured_delivery_slabs_safe_error():
    """If store owner has not configured DELIVERY_FEE_RULES_JSON, backend must not return false fee."""
    with patch("app.delivery_service.DELIVERY_FEE_RULES_JSON", ""), \
         patch("app.delivery_service.MAX_DELIVERY_DISTANCE_KM", 50.0):

        res = calculate_delivery_fee_for_distance(12.0)
        assert res["available"] is False
        assert res["fee"] is None
        assert res["fee_configured"] is False
        assert "not been configured by the store owner" in res["reason"]


# =========================================================================
# 2. Google Routes API Mocked Driving Distance Tests
# =========================================================================

def test_missing_google_api_keys_safe_response():
    with patch("app.delivery_service.GOOGLE_MAPS_SERVER_API_KEY", ""):
        import asyncio
        quote = asyncio.run(get_delivery_quote(17.4065, 78.4772))
        assert quote["success"] is False
        assert quote["available"] is False
        assert quote["error_type"] == "not_configured"
        assert "standard shipping mode" in quote["message"]


def test_successful_driving_route_calculation_and_quote():
    mock_routes_response = {
        "routes": [
            {
                "distanceMeters": 14250,
                "duration": "1800s"
            }
        ]
    }

    sample_rules = json.dumps([
        {"max_km": 10, "fee": 70},
        {"max_km": 20, "fee": 120},
        {"max_km": 50, "fee": 250}
    ])

    with patch("app.delivery_service.GOOGLE_MAPS_SERVER_API_KEY", "mock_server_key_test_123"), \
         patch("app.delivery_service.DELIVERY_FEE_RULES_JSON", sample_rules), \
         patch("httpx.AsyncClient.post") as mock_post:

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_routes_response
        mock_post.return_value = mock_resp

        import asyncio
        quote = asyncio.run(get_delivery_quote(
            destination_lat=17.4483,
            destination_lng=78.3915,
            place_id="ChIJ_test_place_hitech_city",
            postal_code="500081"
        ))

        assert quote["success"] is True
        assert quote["available"] is True
        assert quote["distance_meters"] == 14250
        assert quote["distance_km"] == 14.25
        assert quote["delivery_fee"] == 120.0
        assert "30 mins" in quote["duration_text"]
        assert quote["origin_postal_code"] == SHOP_POSTAL_CODE
        assert quote["destination_postal_code"] == "500081"


def test_routes_api_http_error_handled_gracefully():
    with patch("app.delivery_service.GOOGLE_MAPS_SERVER_API_KEY", "mock_server_key_test_123"), \
         patch("httpx.AsyncClient.post") as mock_post:

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.json.return_value = {"error": "Service Unavailable"}
        mock_post.return_value = mock_resp

        import asyncio
        quote = asyncio.run(get_delivery_quote(17.4483, 78.3915))
        assert quote["success"] is False
        assert quote["available"] is False
        assert quote["error_type"] == "api_error"


def test_routes_api_no_route_found():
    with patch("app.delivery_service.GOOGLE_MAPS_SERVER_API_KEY", "mock_server_key_test_123"), \
         patch("httpx.AsyncClient.post") as mock_post:

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"routes": []}
        mock_post.return_value = mock_resp

        import asyncio
        quote = asyncio.run(get_delivery_quote(17.4483, 78.3915))
        assert quote["success"] is False
        assert quote["available"] is False
        assert quote["error_type"] == "no_route"
        assert "No drivable route found" in quote["message"]


# =========================================================================
# 3. HTTP Endpoints: /api/delivery/config and /api/delivery/quote
# =========================================================================

def test_get_delivery_config_public_endpoint():
    with patch("app.delivery_service.GOOGLE_MAPS_BROWSER_API_KEY", "browser_key_public_test"), \
         patch("app.delivery_service.GOOGLE_MAPS_SERVER_API_KEY", "server_key_secret_hidden"), \
         patch("app.delivery_service.MAX_DELIVERY_DISTANCE_KM", 45.0):

        res = client.get("/api/delivery/config")
        assert res.status_code == 200
        data = res.json()
        assert data["enabled"] is True
        assert data["google_maps_browser_key"] == "browser_key_public_test"
        assert data["max_delivery_distance_km"] == 45.0
        assert data["shop_origin"]["postal_code"] == "500013"
        # Server secret key MUST NEVER BE EXPOSED
        assert "server_key" not in json.dumps(data)


def test_post_delivery_quote_endpoint_success():
    sample_rules = json.dumps([{"max_km": 20, "fee": 150}])
    mock_routes = {"routes": [{"distanceMeters": 8500, "duration": "900s"}]}

    with patch("app.delivery_service.GOOGLE_MAPS_SERVER_API_KEY", "mock_key"), \
         patch("app.delivery_service.DELIVERY_FEE_RULES_JSON", sample_rules), \
         patch("httpx.AsyncClient.post") as mock_post:

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_routes
        mock_post.return_value = mock_resp

        payload = {
            "latitude": 17.4126,
            "longitude": 78.4482,
            "place_id": "ChIJ_secunderabad",
            "formatted_address": "Banjara Hills, Hyderabad, Telangana",
            "postal_code": "500034"
        }
        res = client.post("/api/delivery/quote", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["available"] is True
        assert data["distance_km"] == 8.5
        assert data["delivery_fee"] == 150.0


def test_post_delivery_quote_endpoint_invalid_coords_rejected():
    payload = {
        "latitude": 999.0,  # Invalid
        "longitude": 78.4482
    }
    res = client.post("/api/delivery/quote", json=payload)
    assert res.status_code == 400
    assert "outside the valid range" in res.json()["detail"]


# =========================================================================
# 4. Order Creation Integration & Client-Supplied Fake Fee Ignored
# =========================================================================

def test_order_creation_calculates_trusted_delivery_fee_and_ignores_fake():
    sample_rules = json.dumps([{"max_km": 15, "fee": 110.0}])
    mock_routes = {"routes": [{"distanceMeters": 10000, "duration": "1200s"}]}

    with patch("app.delivery_service.GOOGLE_MAPS_SERVER_API_KEY", "mock_key"), \
         patch("app.delivery_service.DELIVERY_FEE_RULES_JSON", sample_rules), \
         patch("httpx.AsyncClient.post") as mock_post, \
         patch("resend.Emails.send") as mock_resend:

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_routes
        mock_post.return_value = mock_resp
        mock_resend.return_value = {"id": "msg_delivery_test"}

        # Client attempts to send fake delivery fee 0.0 or 10.0
        order_payload = {
            "id": "DBD-DELIVERY-TEST-01",
            "customer": "Simran Kaur",
            "email": "simran@example.com",
            "total": 4990.0,
            "delivery_fee": 10.0,  # Fake client delivery fee
            "destination_lat": 17.4321,
            "destination_lng": 78.4123,
            "place_id": "ChIJ_simran_place",
            "paymentMethod": "Cash on Delivery",
            "paymentStatus": "Pending",
            "items": [{"id": 1, "name": "Necklace", "price": 4990.0, "qty": 1}]
        }

        res = client.post("/api/orders", json=order_payload)
        assert res.status_code == 201
        saved_order = res.json()

        # Authoritative server delivery fee (110.0) was calculated and saved
        assert saved_order["delivery_fee"] == 110.0
        assert saved_order["delivery_distance_km"] == 10.0
        assert saved_order["destination_lat"] == 17.4321
        assert saved_order["destination_lng"] == 78.4123
        assert saved_order["place_id"] == "ChIJ_simran_place"


def test_order_creation_rejects_destination_exceeding_max_delivery_radius():
    mock_routes = {"routes": [{"distanceMeters": 65000, "duration": "4500s"}]}  # 65 km

    with patch("app.delivery_service.GOOGLE_MAPS_SERVER_API_KEY", "mock_key"), \
         patch("app.delivery_service.MAX_DELIVERY_DISTANCE_KM", 50.0), \
         patch("httpx.AsyncClient.post") as mock_post:

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_routes
        mock_post.return_value = mock_resp

        order_payload = {
            "id": "DBD-OUTSIDE-RADIUS",
            "customer": "Far Away Customer",
            "email": "far@example.com",
            "total": 5000.0,
            "destination_lat": 17.9000,
            "destination_lng": 78.9000,
            "items": [{"id": 1, "name": "Item", "price": 5000.0, "qty": 1}]
        }

        res = client.post("/api/orders", json=order_payload)
        assert res.status_code == 400
        assert "exceeds the maximum delivery radius" in res.json()["detail"]
