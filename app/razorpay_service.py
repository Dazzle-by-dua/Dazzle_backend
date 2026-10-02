import os
import re
import logging
from typing import Optional, Dict, Any
import razorpay
from fastapi import HTTPException
from app.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

logger = logging.getLogger("dazzle.razorpay")

_razorpay_state: Dict[str, Any] = {
    "configured": False,
    "verified": False,
    "key_id": None,
    "mode": "test",
    "status": "uninitialized",
    "error": None
}

def _sanitize_razorpay_error(msg: Any) -> str:
    """Mask any API secrets, passwords, or credentials from error messages."""
    text = str(msg)
    if RAZORPAY_KEY_SECRET and RAZORPAY_KEY_SECRET in text:
        text = text.replace(RAZORPAY_KEY_SECRET, "[REDACTED]")
    return text

def is_razorpay_configured() -> bool:
    """Check if Razorpay API keys are configured."""
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)

_razorpay_client_instance: Optional[razorpay.Client] = None

def get_razorpay_client() -> Optional[razorpay.Client]:
    """Get initialized Razorpay Python SDK client."""
    global _razorpay_client_instance
    if not is_razorpay_configured():
        return None
    if _razorpay_client_instance is None:
        try:
            _razorpay_client_instance = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        except Exception as e:
            logger.error(f"Failed to initialize Razorpay client: {_sanitize_razorpay_error(e)}")
            return None
    return _razorpay_client_instance

def verify_razorpay_configuration() -> Dict[str, Any]:
    """
    Verify Razorpay configuration during startup.
    Uses authenticated lightweight query. Logs clear message without exposing secrets.
    """
    global _razorpay_state

    if not is_razorpay_configured():
        _razorpay_state["configured"] = False
        _razorpay_state["verified"] = False
        _razorpay_state["status"] = "not_configured"
        _razorpay_state["error"] = "Razorpay environment variables (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET) not set."
        msg = "Razorpay configuration: None (Credentials not set in environment)"
        print(msg)
        logger.warning(msg)
        return dict(_razorpay_state)

    mode = "test" if RAZORPAY_KEY_ID.startswith("rzp_test_") else "live"
    _razorpay_state["configured"] = True
    _razorpay_state["key_id"] = RAZORPAY_KEY_ID
    _razorpay_state["mode"] = mode

    try:
        client = get_razorpay_client()
        if not client:
            raise ValueError("Could not instantiate Razorpay client.")

        # Lightweight check: Query recent orders with count 1
        client.order.all({"count": 1})

        _razorpay_state["verified"] = True
        _razorpay_state["status"] = "verified"
        _razorpay_state["error"] = None

        success_msg = f"Razorpay configuration detected and verified ({mode.upper()} Mode - Key: {RAZORPAY_KEY_ID[:12]}...)"
        print(success_msg)
        logger.info(success_msg)
        return dict(_razorpay_state)

    except Exception as e:
        safe_err = _sanitize_razorpay_error(e)
        _razorpay_state["verified"] = False
        _razorpay_state["status"] = "failed"
        _razorpay_state["error"] = safe_err

        fail_msg = f"Razorpay configuration verification failed: {safe_err}"
        print(fail_msg)
        logger.warning(fail_msg)
        return dict(_razorpay_state)

def get_razorpay_status() -> Dict[str, Any]:
    """Return safe public Razorpay status (never leaks secret)."""
    return {
        "configured": _razorpay_state.get("configured", False),
        "verified": _razorpay_state.get("verified", False),
        "status": _razorpay_state.get("status", "not_configured"),
        "key_id": RAZORPAY_KEY_ID if is_razorpay_configured() else None,
        "mode": _razorpay_state.get("mode", "test"),
        "currency": "INR"
    }

def create_razorpay_order(
    amount_in_rupees: float,
    receipt: str,
    notes: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Create a server-side order with Razorpay.
    Amount is securely converted to paise (amount * 100).
    """
    if not is_razorpay_configured():
        raise HTTPException(
            status_code=503,
            detail="Razorpay payments are currently unavailable. Missing server configuration."
        )

    client = get_razorpay_client()
    if not client:
        raise HTTPException(status_code=500, detail="Razorpay client unavailable.")

    # Razorpay amount is in paise (1 INR = 100 paise)
    amount_paise = int(round(amount_in_rupees * 100))
    if amount_paise < 100:
        raise HTTPException(status_code=400, detail="Minimum order amount for Razorpay is ₹1.00.")

    order_payload = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": receipt,
        "payment_capture": 1,  # Auto capture payment
        "notes": notes or {}
    }

    try:
        rzp_order = client.order.create(order_payload)
        return {
            "razorpay_order_id": rzp_order["id"],
            "amount": rzp_order["amount"],
            "currency": rzp_order.get("currency", "INR"),
            "receipt": rzp_order.get("receipt", receipt),
            "status": rzp_order.get("status", "created"),
            "key_id": RAZORPAY_KEY_ID
        }
    except Exception as e:
        safe_err = _sanitize_razorpay_error(e)
        logger.error(f"Failed to create Razorpay order: {safe_err}")
        raise HTTPException(
            status_code=502,
            detail=f"Razorpay order creation failed: {safe_err}"
        )

def verify_razorpay_signature(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str
) -> bool:
    """
    Cryptographically verify the Razorpay payment signature using the official SDK.
    Never trusts client input without HMAC-SHA256 signature verification.
    """
    if not is_razorpay_configured():
        raise HTTPException(status_code=503, detail="Razorpay not configured.")

    client = get_razorpay_client()
    if not client:
        raise HTTPException(status_code=500, detail="Razorpay client unavailable.")

    try:
        # Calls client.utility.verify_payment_signature
        result = client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature
        })
        return bool(result)
    except razorpay.errors.SignatureVerificationError as e:
        logger.warning(f"Razorpay signature mismatch for order {razorpay_order_id}: {_sanitize_razorpay_error(e)}")
        return False
    except Exception as e:
        logger.error(f"Error during signature verification: {_sanitize_razorpay_error(e)}")
        return False

def fetch_payment_details(razorpay_payment_id: str) -> Optional[Dict[str, Any]]:
    """Fetch verified payment details from Razorpay API."""
    if not is_razorpay_configured():
        return None

    try:
        client = get_razorpay_client()
        if not client:
            return None
        payment = client.payment.fetch(razorpay_payment_id)
        return {
            "id": payment.get("id"),
            "entity": payment.get("entity"),
            "amount": payment.get("amount", 0) / 100.0,
            "currency": payment.get("currency", "INR"),
            "status": payment.get("status"),
            "method": payment.get("method"),
            "bank": payment.get("bank"),
            "wallet": payment.get("wallet"),
            "vpa": payment.get("vpa"),
            "email": payment.get("email"),
            "contact": payment.get("contact"),
            "created_at": payment.get("created_at")
        }
    except Exception as e:
        logger.warning(f"Could not fetch Razorpay payment {razorpay_payment_id}: {_sanitize_razorpay_error(e)}")
        return None
