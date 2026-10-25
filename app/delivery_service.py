"""
Dazzle by Dua - Delivery & Distance Calculation Service
Calculates driving-route distances from the fixed shop origin (Hyderabad)
to customer delivery destinations using Google Routes API.
Determines delivery availability and fees based on central store slab configurations.
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional, Tuple

import httpx
from app.config import (
    GOOGLE_MAPS_SERVER_API_KEY,
    GOOGLE_MAPS_BROWSER_API_KEY,
    SHOP_LATITUDE,
    SHOP_LONGITUDE,
    SHOP_POSTAL_CODE,
    MAX_DELIVERY_DISTANCE_KM,
    DELIVERY_FEE_RULES_JSON
)

logger = logging.getLogger("dazzle.delivery")

# Google Routes API endpoint (Compute Routes v2)
GOOGLE_ROUTES_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
ROUTES_TIMEOUT_SECONDS = 8.0


def is_routes_api_configured() -> bool:
    """Check if the server-side Google Routes API key is configured."""
    return bool(GOOGLE_MAPS_SERVER_API_KEY and GOOGLE_MAPS_SERVER_API_KEY.strip())


def is_browser_api_configured() -> bool:
    """Check if the browser-side Google Places / Maps API key is configured."""
    return bool(GOOGLE_MAPS_BROWSER_API_KEY and GOOGLE_MAPS_BROWSER_API_KEY.strip())


def get_delivery_config_status() -> Dict[str, Any]:
    """
    Public delivery configuration.
    CRITICAL: Never exposes GOOGLE_MAPS_SERVER_API_KEY.
    Only exposes the browser key if configured.
    """
    rules = get_delivery_fee_rules()
    return {
        "enabled": is_routes_api_configured() or is_browser_api_configured(),
        "google_maps_browser_key": GOOGLE_MAPS_BROWSER_API_KEY if GOOGLE_MAPS_BROWSER_API_KEY else None,
        "shop_origin": {
            "latitude": SHOP_LATITUDE,
            "longitude": SHOP_LONGITUDE,
            "postal_code": SHOP_POSTAL_CODE,
            "city": "Hyderabad",
            "state": "Telangana"
        },
        "max_delivery_distance_km": MAX_DELIVERY_DISTANCE_KM,
        "fee_configured": len(rules) > 0
    }


def validate_coordinates(lat: Any, lng: Any) -> Tuple[bool, str]:
    """Validate latitude and longitude ranges."""
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (ValueError, TypeError):
        return False, "Coordinates must be valid numeric floating-point values."

    if not (-90.0 <= lat_f <= 90.0):
        return False, f"Latitude {lat_f} is outside the valid range (-90.0 to 90.0)."

    if not (-180.0 <= lng_f <= 180.0):
        return False, f"Longitude {lng_f} is outside the valid range (-180.0 to 180.0)."

    if lat_f == 0.0 and lng_f == 0.0:
        return False, "Coordinates (0, 0) point to Null Island and cannot be used for delivery."

    return True, "Valid"


def get_delivery_fee_rules() -> List[Dict[str, float]]:
    """
    Parse and validate delivery fee slabs from DELIVERY_FEE_RULES_JSON.
    Returns a sorted list of slabs: [{'max_km': 5.0, 'fee': 50.0}, ...]
    If not configured or malformed, returns an empty list.
    """
    if not DELIVERY_FEE_RULES_JSON or not DELIVERY_FEE_RULES_JSON.strip():
        return []

    try:
        raw_rules = json.loads(DELIVERY_FEE_RULES_JSON)
        if not isinstance(raw_rules, list):
            logger.warning("DELIVERY_FEE_RULES_JSON is not a list.")
            return []

        parsed_rules = []
        for r in raw_rules:
            if not isinstance(r, dict):
                continue
            max_km = r.get("max_km") or r.get("maxKm")
            fee = r.get("fee")
            if max_km is not None and fee is not None:
                parsed_rules.append({
                    "max_km": float(max_km),
                    "fee": float(fee)
                })

        parsed_rules.sort(key=lambda x: x["max_km"])
        return parsed_rules
    except Exception as e:
        logger.error(f"Failed to parse DELIVERY_FEE_RULES_JSON: {e}")
        return []


def calculate_delivery_fee_for_distance(distance_km: float) -> Dict[str, Any]:
    """
    Determine delivery availability and fee based on calculated driving distance.
    Returns:
    {
        'available': bool,
        'fee': Optional[float],
        'reason': str,
        'fee_configured': bool
    }
    """
    # 1. Check distance against maximum allowed radius
    if distance_km > MAX_DELIVERY_DISTANCE_KM:
        return {
            "available": False,
            "fee": None,
            "reason": f"Delivery unavailable: Destination is {distance_km:.1f} km away, which exceeds the maximum delivery radius of {MAX_DELIVERY_DISTANCE_KM} km.",
            "fee_configured": True
        }

    # 2. Check if fee rules are configured by store owner
    rules = get_delivery_fee_rules()
    if not rules:
        return {
            "available": False,
            "fee": None,
            "reason": "Delivery fee slabs have not been configured by the store owner. Please configure DELIVERY_FEE_RULES_JSON.",
            "fee_configured": False
        }

    # 3. Match distance to slab
    for slab in rules:
        if distance_km <= slab["max_km"]:
            fee = slab["fee"]
            return {
                "available": True,
                "fee": fee,
                "reason": f"Delivery available (₹{fee:,.2f}) for {distance_km:.1f} km driving distance.",
                "fee_configured": True
            }

    # 4. If distance <= MAX_DELIVERY_DISTANCE_KM but exceeds highest defined slab,
    # use highest slab fee
    highest_slab = rules[-1]
    fee = highest_slab["fee"]
    return {
        "available": True,
        "fee": fee,
        "reason": f"Delivery available (₹{fee:,.2f}) for {distance_km:.1f} km driving distance.",
        "fee_configured": True
    }


def parse_duration_seconds(duration_str: Optional[str]) -> Optional[int]:
    """Parse Google Routes API duration format (e.g. '1420s') into integer seconds."""
    if not duration_str:
        return None
    match = re.match(r"^(\d+)s$", str(duration_str).strip())
    if match:
        return int(match.group(1))
    return None


def format_duration_text(seconds: Optional[int]) -> str:
    """Format duration seconds into human-readable text (e.g. '35 mins', '1 hr 15 mins')."""
    if seconds is None or seconds <= 0:
        return "Approx. 30-45 mins"
    mins = round(seconds / 60)
    if mins < 60:
        return f"{mins} mins"
    hours = mins // 60
    rem_mins = mins % 60
    if rem_mins > 0:
        return f"{hours} hr {rem_mins} mins"
    return f"{hours} hr"


async def compute_driving_route_distance(
    destination_lat: float,
    destination_lng: float
) -> Dict[str, Any]:
    """
    Call Google Routes API v2 to calculate authoritative driving-route distance
    from fixed shop origin (SHOP_LATITUDE, SHOP_LONGITUDE) to destination.
    Never trusts straight-line distance.
    Returns:
    {
        'success': bool,
        'distance_meters': int,
        'distance_km': float,
        'duration_seconds': int,
        'duration_text': str,
        'error_type': Optional[str],
        'error_message': Optional[str]
    }
    """
    # Coordinate range validation
    is_valid, validation_msg = validate_coordinates(destination_lat, destination_lng)
    if not is_valid:
        return {
            "success": False,
            "error_type": "invalid_coordinates",
            "error_message": validation_msg
        }

    # Configuration check
    if not is_routes_api_configured():
        return {
            "success": False,
            "error_type": "not_configured",
            "error_message": "Google Maps Routes API is not configured on the server. GOOGLE_MAPS_SERVER_API_KEY is missing."
        }

    request_payload = {
        "origin": {
            "location": {
                "latLng": {
                    "latitude": SHOP_LATITUDE,
                    "longitude": SHOP_LONGITUDE
                }
            }
        },
        "destination": {
            "location": {
                "latLng": {
                    "latitude": destination_lat,
                    "longitude": destination_lng
                }
            }
        },
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE"
    }

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_SERVER_API_KEY,
        "X-Goog-FieldMask": "routes.distanceMeters,routes.duration"
    }

    try:
        async with httpx.AsyncClient(timeout=ROUTES_TIMEOUT_SECONDS) as client:
            response = await client.post(
                GOOGLE_ROUTES_API_URL,
                json=request_payload,
                headers=headers
            )

        if response.status_code != 200:
            logger.warning(f"Google Routes API error: HTTP {response.status_code}")
            return {
                "success": False,
                "error_type": "api_error",
                "error_message": f"Routes service returned HTTP status {response.status_code}."
            }

        data = response.json()
        routes = data.get("routes")
        if not routes or len(routes) == 0:
            return {
                "success": False,
                "error_type": "no_route",
                "error_message": "No driving route could be found between store origin and destination."
            }

        primary_route = routes[0]
        distance_meters = int(primary_route.get("distanceMeters", 0))
        distance_km = round(distance_meters / 1000.0, 2)
        duration_raw = primary_route.get("duration")
        duration_seconds = parse_duration_seconds(duration_raw)
        duration_text = format_duration_text(duration_seconds)

        return {
            "success": True,
            "distance_meters": distance_meters,
            "distance_km": distance_km,
            "duration_seconds": duration_seconds,
            "duration_text": duration_text
        }

    except httpx.TimeoutException:
        logger.warning("Timeout while contacting Google Routes API.")
        return {
            "success": False,
            "error_type": "timeout",
            "error_message": "Driving route calculation timed out. Please try again."
        }
    except Exception as err:
        logger.error(f"Unexpected error communicating with Google Routes API: {err}")
        return {
            "success": False,
            "error_type": "request_failed",
            "error_message": "Unable to calculate route distance at this time."
        }


async def get_delivery_quote(
    destination_lat: float,
    destination_lng: float,
    place_id: Optional[str] = None,
    formatted_address: Optional[str] = None,
    postal_code: Optional[str] = None
) -> Dict[str, Any]:
    """
    High-level delivery quote function:
    1. Validates destination.
    2. Computes driving distance via Google Routes API.
    3. Calculates applicable delivery charge and availability.
    4. Returns complete, safe response.
    """
    route_result = await compute_driving_route_distance(destination_lat, destination_lng)

    if not route_result["success"]:
        error_type = route_result.get("error_type", "error")
        error_msg = route_result.get("error_message", "Route calculation failed.")

        # Friendly messages for customer checkout
        if error_type == "not_configured":
            friendly_message = "Delivery distance service is currently running in standard shipping mode."
        elif error_type == "no_route":
            friendly_message = "No drivable route found for this location. Please check your address."
        else:
            friendly_message = f"Unable to calculate driving route: {error_msg}"

        return {
            "success": False,
            "available": False,
            "distance_km": None,
            "distance_meters": None,
            "delivery_fee": None,
            "duration_text": None,
            "message": friendly_message,
            "origin_postal_code": SHOP_POSTAL_CODE,
            "destination_postal_code": postal_code,
            "fee_configured": len(get_delivery_fee_rules()) > 0,
            "error_type": error_type
        }

    distance_km = route_result["distance_km"]
    distance_meters = route_result["distance_meters"]
    duration_text = route_result["duration_text"]

    fee_result = calculate_delivery_fee_for_distance(distance_km)

    return {
        "success": True,
        "available": fee_result["available"],
        "distance_km": distance_km,
        "distance_meters": distance_meters,
        "delivery_fee": fee_result["fee"],
        "duration_text": duration_text,
        "message": fee_result["reason"],
        "origin_postal_code": SHOP_POSTAL_CODE,
        "destination_postal_code": postal_code,
        "fee_configured": fee_result["fee_configured"]
    }
