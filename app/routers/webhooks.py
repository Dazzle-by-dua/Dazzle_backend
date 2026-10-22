import json
import logging
import datetime
from fastapi import APIRouter, Request, HTTPException, Header
from app.database import get_database, clean_doc
from app.razorpay_service import (
    verify_razorpay_webhook_signature,
    is_razorpay_webhook_configured,
    is_razorpay_configured
)

logger = logging.getLogger("dazzle.webhooks")

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

@router.post("/razorpay")
async def handle_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(None, alias="X-Razorpay-Signature")
):
    """
    Production-ready Razorpay webhook receiver.
    Verifies raw body signature, ensures idempotency, and updates orders atomically.
    Never downgrades an already confirmed 'Paid' order.
    """
    if not x_razorpay_signature:
        logger.warning("Razorpay webhook received without X-Razorpay-Signature header.")
        raise HTTPException(status_code=400, detail="Missing X-Razorpay-Signature header.")

    # 1. Read raw binary body for HMAC validation
    raw_body = await request.body()
    if not raw_body:
        raise HTTPException(status_code=400, detail="Empty webhook payload.")

    # 2. Cryptographically verify signature
    is_valid = verify_razorpay_webhook_signature(raw_body=raw_body, signature=x_razorpay_signature)
    if not is_valid:
        logger.warning("Razorpay webhook signature verification failed.")
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    # 3. Parse JSON event payload
    try:
        event_payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        logger.error(f"Malformed JSON in webhook payload: {e}")
        raise HTTPException(status_code=400, detail="Malformed JSON payload.")

    event_id = event_payload.get("event_id") or event_payload.get("id") or request.headers.get("X-Razorpay-Event-Id")
    event_name = event_payload.get("event")
    logger.info(f"Received verified Razorpay webhook event: {event_name} (Event ID: {event_id})")

    db = get_database()

    # 4. Idempotency Check: Prevent duplicate processing of the same event
    if event_id:
        existing_event = await db.processed_webhooks.find_one({"event_id": event_id})
        if existing_event:
            logger.info(f"Webhook event {event_id} has already been processed. Returning 200 OK.")
            return {"status": "ok", "message": "Event already processed", "event": event_name}

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 5. Handle supported events
    if event_name in ["payment.captured", "order.paid"]:
        # Extract payment entity
        payment_entity = event_payload.get("payload", {}).get("payment", {}).get("entity", {})
        order_entity = event_payload.get("payload", {}).get("order", {}).get("entity", {})

        rzp_order_id = payment_entity.get("order_id") or order_entity.get("id")
        rzp_payment_id = payment_entity.get("id")
        notes = payment_entity.get("notes", {}) or order_entity.get("notes", {})
        internal_order_id = notes.get("order_id") or order_entity.get("receipt")

        order = None
        if internal_order_id:
            order = await db.orders.find_one({"id": internal_order_id})
        if not order and rzp_order_id:
            order = await db.orders.find_one({"razorpay_order_id": rzp_order_id})

        if order:
            # Prevent duplicate confirmation
            if order.get("paymentStatus") == "Paid":
                logger.info(f"Order {order['id']} is already marked as Paid.")
            else:
                method = payment_entity.get("method")
                pay_method_label = f"Razorpay ({method.upper()})" if method else "Razorpay Online"
                await db.orders.update_one(
                    {"id": order["id"]},
                    {
                        "$set": {
                            "status": "Processing",
                            "paymentStatus": "Paid",
                            "paymentMethod": pay_method_label,
                            "razorpay_payment_id": rzp_payment_id or order.get("razorpay_payment_id"),
                            "razorpay_order_id": rzp_order_id or order.get("razorpay_order_id"),
                            "paid_at": now_iso,
                            "updated_at": now_iso
                        }
                    }
                )
                logger.info(f"Order {order['id']} successfully updated to Paid & Processing via webhook {event_name}.")

    elif event_name in ["payment.failed"]:
        payment_entity = event_payload.get("payload", {}).get("payment", {}).get("entity", {})
        rzp_order_id = payment_entity.get("order_id")
        rzp_payment_id = payment_entity.get("id")
        notes = payment_entity.get("notes", {})
        internal_order_id = notes.get("order_id")

        order = None
        if internal_order_id:
            order = await db.orders.find_one({"id": internal_order_id})
        if not order and rzp_order_id:
            order = await db.orders.find_one({"razorpay_order_id": rzp_order_id})

        if order:
            # CRITICAL: Never downgrade an already confirmed Paid order to Failed!
            if order.get("paymentStatus") == "Paid":
                logger.info(f"Late failure event received for order {order['id']}, but order is already Paid. Ignored.")
            else:
                error_info = {
                    "code": payment_entity.get("error_code"),
                    "description": payment_entity.get("error_description"),
                    "reason": payment_entity.get("error_reason"),
                    "payment_id": rzp_payment_id
                }
                await db.orders.update_one(
                    {"id": order["id"]},
                    {
                        "$set": {
                            "paymentStatus": "Failed",
                            "paymentError": error_info,
                            "updated_at": now_iso
                        }
                    }
                )
                logger.info(f"Order {order['id']} marked as Failed via webhook.")

    # 6. Save event to deduplication store
    if event_id:
        try:
            await db.processed_webhooks.insert_one({
                "event_id": event_id,
                "event": event_name,
                "processed_at": now_iso
            })
        except Exception as e:
            logger.warning(f"Could not persist processed webhook event {event_id}: {e}")

    return {"status": "ok", "event": event_name}
