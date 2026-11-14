import hmac
import hashlib
import json
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from app.main import app
from app.database import get_database

client = TestClient(app)

def compute_signature(order_id: str, payment_id: str, secret: str = "rzp_test_secret_mock_12345") -> str:
    msg = f"{order_id}|{payment_id}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

def compute_webhook_signature(raw_body: bytes, secret: str = "rzp_webhook_secret_mock_12345") -> str:
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

@pytest.fixture(autouse=True)
def mock_razorpay_env():
    with patch("app.razorpay_service.is_razorpay_configured", return_value=True), \
         patch("app.razorpay_service.RAZORPAY_KEY_ID", "rzp_test_mock_123"), \
         patch("app.razorpay_service.RAZORPAY_KEY_SECRET", "rzp_test_secret_mock_12345"), \
         patch("app.razorpay_service.RAZORPAY_WEBHOOK_SECRET", "rzp_webhook_secret_mock_12345"), \
         patch("app.routers.webhooks.is_razorpay_configured", return_value=True):
        yield

def test_order_creation_does_not_send_admin_email():
    """
    Scenario: Customer initiates checkout.
    Requirement: Order created in status 'Payment Pending', no admin email sent.
    """
    mock_rzp_order = {
        "id": "order_test_no_email_1",
        "amount": 499000,
        "currency": "INR",
        "receipt": "DBD-TEST-1",
        "status": "created"
    }

    with patch("app.razorpay_service.get_razorpay_client") as mock_client, \
         patch("app.resend_service.resend.Emails.send") as mock_email_send:

        mock_client.return_value.order.create.return_value = mock_rzp_order

        res = client.post("/api/orders/razorpay/create-order", json={
            "items": [{"id": 1, "qty": 1}],
            "customer": "Amina",
            "email": "amina@example.com",
            "phone": "+91 99999 88888",
            "address": "Road 10, Jubilee Hills",
            "landmark": "Near Checkpost",
            "city": "Hyderabad",
            "state": "Telangana",
            "postal_code": "500033"
        })

        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        order_id = data["order_id"]

        # CRITICAL: No admin email notification must have been sent
        assert mock_email_send.call_count == 0

        # Verify DB status
        db = get_database()
        import asyncio
        db_order = asyncio.run(db.orders.find_one({"id": order_id}))
        assert db_order["paymentStatus"] == "Pending"
        assert db_order["status"] == "Payment Pending"
        assert db_order.get("notifications", {}).get("admin_new_order_sent") is not True

def test_payment_failure_and_abandonment_sends_no_admin_email():
    """
    Scenario: Payment fails or modal is closed/dismissed.
    Requirement: Status is Failed, no admin email sent, inventory untouched.
    """
    mock_rzp_order = {
        "id": "order_test_fail_1",
        "amount": 499000,
        "currency": "INR",
        "receipt": "DBD-TEST-2",
        "status": "created"
    }

    with patch("app.razorpay_service.get_razorpay_client") as mock_client, \
         patch("app.resend_service.resend.Emails.send") as mock_email_send:

        mock_client.return_value.order.create.return_value = mock_rzp_order

        res = client.post("/api/orders/razorpay/create-order", json={
            "items": [{"id": 1, "qty": 1}],
            "customer": "Amina",
            "email": "amina@example.com",
            "phone": "+91 99999 88888",
            "address": "Road 10, Jubilee Hills",
            "landmark": "Near Checkpost",
            "city": "Hyderabad",
            "state": "Telangana"
        })
        order_id = res.json()["order_id"]
        rzp_order_id = res.json()["razorpay_order_id"]

        # Record payment failure / modal dismissed
        fail_res = client.post("/api/orders/razorpay/payment-failed", json={
            "order_id": order_id,
            "razorpay_order_id": rzp_order_id,
            "error_reason": "Payment cancelled by user"
        })
        assert fail_res.status_code == 200
        assert mock_email_send.call_count == 0

        db = get_database()
        import asyncio
        db_order = asyncio.run(db.orders.find_one({"id": order_id}))
        assert db_order["paymentStatus"] == "Failed"
        assert db_order.get("inventory_deducted") is not True

def test_successful_payment_verification_and_single_admin_email():
    """
    Scenario: Customer pays successfully, signature verified server-side.
    Requirement: Order updated to Paid/Processing, exactly 1 admin email sent, stock deducted once.
    Duplicate callback: returns success, no duplicate email, no duplicate stock deduction.
    """
    mock_rzp_order = {
        "id": "order_test_success_1",
        "amount": 504000,
        "currency": "INR",
        "receipt": "DBD-TEST-3",
        "status": "created"
    }

    with patch("app.razorpay_service.get_razorpay_client") as mock_client, \
         patch("app.resend_service.resend.Emails.send") as mock_email_send, \
         patch("app.routers.orders.fetch_payment_details") as mock_fetch_payment:

        mock_client.return_value.order.create.return_value = mock_rzp_order
        mock_email_send.return_value = {"id": "re_mock_test_123"}
        mock_fetch_payment.return_value = {
            "id": "pay_test_succ_123",
            "amount": 5040.0,
            "currency": "INR",
            "status": "captured",
            "method": "upi"
        }

        res = client.post("/api/orders/razorpay/create-order", json={
            "items": [{"id": 1, "qty": 1}],
            "customer": "Sara",
            "email": "sara@example.com",
            "phone": "+91 99999 77777",
            "address": "Banjara Hills",
            "landmark": "Near Taj Krishna",
            "city": "Hyderabad",
            "state": "Telangana"
        })
        order_id = res.json()["order_id"]
        rzp_order_id = res.json()["razorpay_order_id"]
        pay_id = "pay_test_succ_123"
        sig = compute_signature(rzp_order_id, pay_id)

        # Pre-verification: 0 emails
        assert mock_email_send.call_count == 0

        # Verify payment
        v_res = client.post("/api/orders/razorpay/verify", json={
            "order_id": order_id,
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig
        })
        assert v_res.status_code == 200
        assert v_res.json()["success"] is True

        # Exactly 1 admin email sent
        assert mock_email_send.call_count == 1

        db = get_database()
        import asyncio
        db_order = asyncio.run(db.orders.find_one({"id": order_id}))
        assert db_order["paymentStatus"] == "Paid"
        assert db_order["status"] == "Processing"
        assert db_order["inventory_deducted"] is True
        assert db_order["razorpay_payment_id"] == pay_id

        # Duplicate verification callback
        v_dup = client.post("/api/orders/razorpay/verify", json={
            "order_id": order_id,
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig
        })
        assert v_dup.status_code == 200
        assert v_dup.json()["success"] is True
        # Email count remains 1 (no duplicate email)
        assert mock_email_send.call_count == 1

def test_webhook_payment_captured_and_frontend_replay():
    """
    Scenario: Webhook payment.captured arrives before frontend verification.
    Requirement: Webhook verifies and confirms order, sends 1 email. Frontend replay handles idempotently.
    """
    mock_rzp_order = {
        "id": "order_test_wh_first_1",
        "amount": 504000,
        "currency": "INR",
        "receipt": "DBD-TEST-4",
        "status": "created"
    }

    with patch("app.razorpay_service.get_razorpay_client") as mock_client, \
         patch("app.resend_service.resend.Emails.send") as mock_email_send, \
         patch("app.routers.orders.fetch_payment_details") as mock_fetch_payment:

        mock_client.return_value.order.create.return_value = mock_rzp_order
        mock_email_send.return_value = {"id": "re_mock_wh_123"}
        mock_fetch_payment.return_value = {
            "id": "pay_wh_first_123",
            "amount": 5040.0,
            "currency": "INR",
            "status": "captured",
            "method": "card"
        }

        res = client.post("/api/orders/razorpay/create-order", json={
            "items": [{"id": 1, "qty": 1}],
            "customer": "Fatima",
            "email": "fatima@example.com",
            "phone": "+91 99999 66666",
            "address": "Madhapur",
            "landmark": "Near Metro",
            "city": "Hyderabad",
            "state": "Telangana"
        })
        order_id = res.json()["order_id"]
        rzp_order_id = res.json()["razorpay_order_id"]
        pay_id = "pay_wh_first_123"

        # Webhook arrives first
        webhook_event = {
            "event_id": f"evt_test_wh_{order_id}",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "order_id": rzp_order_id,
                        "amount": 504000,
                        "currency": "INR",
                        "status": "captured",
                        "method": "card",
                        "notes": {"order_id": order_id}
                    }
                }
            }
        }
        raw_body = json.dumps(webhook_event).encode("utf-8")
        wh_sig = compute_webhook_signature(raw_body)

        wh_res = client.post(
            "/api/webhooks/razorpay",
            content=raw_body,
            headers={"X-Razorpay-Signature": wh_sig, "Content-Type": "application/json"}
        )
        assert wh_res.status_code == 200
        assert mock_email_send.call_count == 1

        # Frontend callback arrives afterwards
        sig = compute_signature(rzp_order_id, pay_id)
        fe_res = client.post("/api/orders/razorpay/verify", json={
            "order_id": order_id,
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig
        })
        assert fe_res.status_code == 200
        assert fe_res.json()["success"] is True
        # Email call count is still exactly 1!
        assert mock_email_send.call_count == 1
