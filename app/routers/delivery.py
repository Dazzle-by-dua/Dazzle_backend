"""
Dazzle by Dua - Delivery Router
Handles delivery distance quotes via Google Routes API and provides public delivery config.
"""

import logging
from fastapi import APIRouter, HTTPException, status
from app.models.schemas import (
    DeliveryQuoteRequest,
    DeliveryQuoteResponse,
    DeliveryConfigResponse
)
from app.delivery_service import (
    get_delivery_quote,
    get_delivery_config_status,
    validate_coordinates
)

logger = logging.getLogger("dazzle.delivery_router")

router = APIRouter(prefix="/api/delivery", tags=["Delivery"])


@router.get("/config", response_model=DeliveryConfigResponse)
def get_delivery_public_config():
    """
    Return public delivery configuration (Google Maps browser key, shop origin, max radius).
    The private server-side Routes API key is NEVER exposed.
    """
    return get_delivery_config_status()


@router.post("/quote", response_model=DeliveryQuoteResponse)
async def create_delivery_quote(payload: DeliveryQuoteRequest):
    """
    Calculate driving-route distance from the shop's fixed origin (Hyderabad)
    to the customer's selected destination using Google Routes API, and determine the delivery fee.
    Never trusts client-calculated distance or fees.
    """
    is_valid, validation_msg = validate_coordinates(payload.latitude, payload.longitude)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=validation_msg
        )

    try:
        quote = await get_delivery_quote(
            destination_lat=payload.latitude,
            destination_lng=payload.longitude,
            place_id=payload.place_id,
            formatted_address=payload.formatted_address,
            postal_code=payload.postal_code
        )
        return quote
    except Exception as err:
        logger.error(f"Unexpected error in delivery quote endpoint: {err}")
        return {
            "success": False,
            "available": False,
            "distance_km": None,
            "distance_meters": None,
            "delivery_fee": None,
            "duration_text": None,
            "message": "Delivery service is temporarily unable to calculate route. Please try again or use standard delivery.",
            "origin_postal_code": "500013",
            "destination_postal_code": payload.postal_code,
            "fee_configured": False,
            "error_type": "internal_error"
        }
