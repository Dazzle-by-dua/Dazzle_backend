import hmac
import hashlib
import json
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

from app.main import app
from app.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET

from tests.conftest import TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD

client = TestClient(app)

@pytest.fixture(scope="session", autouse=True)
def app_lifespan():
    with client:
        yield

@pytest.fixture(autouse=True)
def reset_db_state():
    login_res = client.post("/api/auth/login", json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD})
    if login_res.status_code == 200:
        token = login_res.json().get("token")
        if token:
            client.post("/api/backup/reset", headers={"Authorization": f"Bearer {token}"})

def get_auth_headers():
    login_res = client.post("/api/auth/login", json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD})
    token = login_res.json().get("token")
    return {"Authorization": f"Bearer {token}"}

def compute_payment_signature(rzp_order_id: str, rzp_payment_id: str, secret: str = None) -> str:
    sec = secret or RAZORPAY_KEY_SECRET or "test_secret_key"
    msg = f"{rzp_order_id}|{rzp_payment_id}".encode("utf-8")
    return hmac.new(sec.encode("utf-8"), msg, hashlib.sha256).hexdigest()

def compute_webhook_signature(raw_body: bytes, secret: str = None) -> str:
    sec = secret or RAZORPAY_WEBHOOK_SECRET or RAZORPAY_KEY_SECRET or "test_secret_key"
    return hmac.new(sec.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

# =========================================================================
# 1. Config & Public Endpoints
# =========================================================================
def test_razorpay_public_config():
    res = client.get("/api/orders/razorpay/config")
    assert res.status_code == 200
    data = res.json()
    assert "currency" in data
    assert data["currency"] == "INR"
    assert "status" in data
    assert "key_id" in data
    # Ensure sensitive secret is never leaked
    assert "secret" not in data
    assert "RAZORPAY_KEY_SECRET" not in str(data)

# =========================================================================
# 2. Order Creation, Trusted Pricing, & Paise Conversion
# =========================================================================
def test_create_order_trusted_pricing_and_paise_conversion():
    # Attempt price tampering: send price 1.0 instead of actual DB price (4990)
    payload = {
        "items": [
            {"id": 1, "name": "Tampered Necklace", "price": 1.0, "qty": 1, "variant": "Gold"}
        ],
        "customer": "Amina Begum",
        "email": "amina@example.com",
        "phone": "+91 91234 56789",
        "address": "Bandra West, Mumbai",
        "notes": "Please gift wrap"
    }

    mock_rzp_order = {
        "id": "order_test_12345",
        "amount": 499000, # In paise (₹4,990.00)
        "currency": "INR",
        "receipt": "DBD-2026-TEST",
        "status": "created"
    }

    with patch("app.razorpay_service.is_razorpay_configured", return_value=True), \
         patch("app.razorpay_service.get_razorpay_client") as mock_client:
        mock_client.return_value.order.create.return_value = mock_rzp_order

        res = client.post("/api/orders/razorpay/create-order", json=payload)
        assert res.status_code == 200
        data = res.json()

        assert data["success"] is True
        assert data["razorpay_order_id"] == "order_test_12345"
        # Total trusted amount calculated from MongoDB (4990)
        assert data["total"] == 4990.0
        # Amount sent to Razorpay modal is in paise
        assert data["amount"] == 499000
        assert data["currency"] == "INR"
        assert "order_id" in data

        # Verify order in DB via admin authenticated endpoint
        headers = get_auth_headers()
        order_res = client.get(f"/api/orders/{data['order_id']}", headers=headers)
        assert order_res.status_code == 200
        db_order = order_res.json()
        assert db_order["total"] == 4990.0
        assert db_order["paymentStatus"] == "Pending"
        assert db_order["status"] == "Payment Pending"

        # Also verify customer public payment-status endpoint
        pub_status = client.get(f"/api/orders/{data['order_id']}/payment-status")
        assert pub_status.status_code == 200
        assert pub_status.json()["paymentStatus"] == "Pending"

# =========================================================================
# 3. Invalid Product IDs, Quantities & Empty Cart Rejections
# =========================================================================
def test_create_order_invalid_inputs_rejection():
    # Empty cart
    res_empty = client.post("/api/orders/razorpay/create-order", json={
        "items": [],
        "customer": "Amina",
        "email": "amina@example.com"
    })
    assert res_empty.status_code == 400

    # Non-existent product ID
    res_non_exist = client.post("/api/orders/razorpay/create-order", json={
        "items": [{"id": 999999, "qty": 1}],
        "customer": "Amina",
        "email": "amina@example.com"
    })
    assert res_non_exist.status_code == 400
    assert "does not exist" in res_non_exist.json()["detail"].lower()

    # Invalid / Zero / Negative quantity
    res_neg_qty = client.post("/api/orders/razorpay/create-order", json={
        "items": [{"id": 1, "qty": 0}],
        "customer": "Amina",
        "email": "amina@example.com"
    })
    assert res_neg_qty.status_code == 400

# =========================================================================
# 4. Out-of-Stock Product Rejection
# =========================================================================
def test_create_order_out_of_stock_rejection():
    # Toggle product 1 to out of stock
    login = client.post("/api/auth/login", json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD})
    token = login.json()["token"]
    client.patch("/api/products/1/stock", json={"inStock": False}, headers={"Authorization": f"Bearer {token}"})

    payload = {
        "items": [{"id": 1, "qty": 1}],
        "customer": "Amina",
        "email": "amina@example.com"
    }
    res = client.post("/api/orders/razorpay/create-order", json=payload)
    assert res.status_code == 400
    assert "out of stock" in res.json()["detail"].lower()

# =========================================================================
# 5. Invalid & Valid Signature Verification
# =========================================================================
def test_verify_payment_signatures_and_idempotency():
    # 1. Create order
    mock_rzp_order = {
        "id": "order_sig_test_100",
        "amount": 499000,
        "currency": "INR",
        "receipt": "DBD-2026-SIG",
        "status": "created"
    }

    with patch("app.razorpay_service.is_razorpay_configured", return_value=True), \
         patch("app.razorpay_service.get_razorpay_client") as mock_client:
        mock_client.return_value.order.create.return_value = mock_rzp_order

        create_res = client.post("/api/orders/razorpay/create-order", json={
            "items": [{"id": 1, "qty": 1}],
            "customer": "Fatima",
            "email": "fatima@example.com"
        })
        assert create_res.status_code == 200
        order_info = create_res.json()
        internal_id = order_info["order_id"]
        rzp_order_id = order_info["razorpay_order_id"]

    # 2. Test Invalid Signature Rejection
    fake_verify_payload = {
        "order_id": internal_id,
        "razorpay_order_id": rzp_order_id,
        "razorpay_payment_id": "pay_test_999",
        "razorpay_signature": "invalid_forged_signature_hex"
    }
    with patch("app.razorpay_service.is_razorpay_configured", return_value=True):
        res_fail = client.post("/api/orders/razorpay/verify", json=fake_verify_payload)
        assert res_fail.status_code == 400
        assert "verification failed" in res_fail.json()["detail"].lower()

    # 3. Test Valid Signature Verification
    valid_payment_id = "pay_test_valid_888"
    valid_sig = compute_payment_signature(rzp_order_id, valid_payment_id)

    valid_payload = {
        "order_id": internal_id,
        "razorpay_order_id": rzp_order_id,
        "razorpay_payment_id": valid_payment_id,
        "razorpay_signature": valid_sig
    }

    mock_pay_details = {
        "id": valid_payment_id,
        "amount": 4990.0,
        "currency": "INR",
        "status": "captured",
        "method": "upi"
    }

    with patch("app.razorpay_service.is_razorpay_configured", return_value=True), \
         patch("app.routers.orders.fetch_payment_details", return_value=mock_pay_details):

        # Test dual route /api/orders/razorpay/verify
        res_verify = client.post("/api/orders/razorpay/verify", json=valid_payload)
        assert res_verify.status_code == 200
        data = res_verify.json()
        assert data["success"] is True
        assert data["order"]["paymentStatus"] == "Paid"
        assert data["order"]["status"] == "Processing"
        assert data["order"]["razorpay_payment_id"] == valid_payment_id

        # 4. Duplicate Verification (Idempotency)
        res_dup = client.post("/api/orders/razorpay/verify", json=valid_payload)
        assert res_dup.status_code == 200
        assert "already verified" in res_dup.json()["message"].lower()

# =========================================================================
# 6. Payment Amount / Currency Mismatch Rejection
# =========================================================================
def test_verify_payment_amount_and_currency_mismatch():
    mock_rzp_order = {
        "id": "order_mismatch_100",
        "amount": 499000,
        "currency": "INR",
        "receipt": "DBD-2026-MISMATCH",
        "status": "created"
    }

    with patch("app.razorpay_service.is_razorpay_configured", return_value=True), \
         patch("app.razorpay_service.get_razorpay_client") as mock_client:
        mock_client.return_value.order.create.return_value = mock_rzp_order

        create_res = client.post("/api/orders/razorpay/create-order", json={
            "items": [{"id": 1, "qty": 1}],
            "customer": "Zoya",
            "email": "zoya@example.com"
        })
        order_info = create_res.json()

    valid_sig = compute_payment_signature(order_info["razorpay_order_id"], "pay_mismatch_1")

    # Amount mismatch: Gateway says paid 1000 instead of 4990
    mismatch_details = {
        "id": "pay_mismatch_1",
        "amount": 1000.0,
        "currency": "INR",
        "status": "captured",
        "method": "card"
    }

    with patch("app.razorpay_service.is_razorpay_configured", return_value=True), \
         patch("app.routers.orders.fetch_payment_details", return_value=mismatch_details):

        res = client.post("/api/orders/razorpay/verify", json={
            "order_id": order_info["order_id"],
            "razorpay_order_id": order_info["razorpay_order_id"],
            "razorpay_payment_id": "pay_mismatch_1",
            "razorpay_signature": valid_sig
        })
        assert res.status_code == 400
        assert "amount mismatch" in res.json()["detail"].lower()

# =========================================================================
# 7. Payment Failure Tracking & Protection
# =========================================================================
def test_payment_failure_tracking_and_no_overwrite_paid():
    # 1. Create order
    mock_rzp_order = {"id": "order_fail_1", "amount": 499000, "currency": "INR", "receipt": "DBD-FAIL", "status": "created"}
    with patch("app.razorpay_service.is_razorpay_configured", return_value=True), \
         patch("app.razorpay_service.get_razorpay_client") as mock_client:
        mock_client.return_value.order.create.return_value = mock_rzp_order
        c_res = client.post("/api/orders/razorpay/create-order", json={"items": [{"id": 1, "qty": 1}], "customer": "Sara", "email": "sara@example.com"})
        order = c_res.json()

    # Record failure
    res_fail = client.post("/api/orders/razorpay/payment-failed", json={
        "order_id": order["order_id"],
        "razorpay_order_id": order["razorpay_order_id"],
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "User cancelled in modal",
        "error_reason": "payment_cancelled"
    })
    assert res_fail.status_code == 200

    # Verify status is Failed
    status_res = client.get(f"/api/orders/{order['order_id']}/payment-status")
    assert status_res.status_code == 200
    assert status_res.json()["paymentStatus"] == "Failed"

    # Now verify the order as Paid
    valid_sig = compute_payment_signature(order["razorpay_order_id"], "pay_success_after_fail")
    with patch("app.razorpay_service.is_razorpay_configured", return_value=True), \
         patch("app.razorpay_service.fetch_payment_details", return_value={"amount": 4990.0, "currency": "INR", "method": "upi"}):
        client.post("/api/orders/razorpay/verify", json={
            "order_id": order["order_id"],
            "razorpay_order_id": order["razorpay_order_id"],
            "razorpay_payment_id": "pay_success_after_fail",
            "razorpay_signature": valid_sig
        })

    # A subsequent failure attempt MUST NOT overwrite Paid
    res_late_fail = client.post("/api/orders/razorpay/payment-failed", json={
        "order_id": order["order_id"],
        "error_reason": "late_network_error"
    })
    assert res_late_fail.status_code == 200

    check_res = client.get(f"/api/orders/{order['order_id']}/payment-status")
    assert check_res.json()["paymentStatus"] == "Paid"

# =========================================================================
# 8. Webhook Endpoints & Deduplication
# =========================================================================
def test_razorpay_webhooks_flow_and_deduplication():
    # 1. Create order in MongoDB
    mock_rzp_order = {"id": "order_wh_1", "amount": 499000, "currency": "INR", "receipt": "DBD-WH", "status": "created"}
    with patch("app.razorpay_service.is_razorpay_configured", return_value=True), \
         patch("app.razorpay_service.get_razorpay_client") as mock_client:
        mock_client.return_value.order.create.return_value = mock_rzp_order
        c_res = client.post("/api/orders/razorpay/create-order", json={"items": [{"id": 1, "qty": 1}], "customer": "Noor", "email": "noor@example.com"})
        internal_id = c_res.json()["order_id"]

    # 2. Missing signature
    res_no_sig = client.post("/api/webhooks/razorpay", content=b"{}")
    assert res_no_sig.status_code == 400

    # 3. Invalid signature
    res_bad_sig = client.post("/api/webhooks/razorpay", content=b"{}", headers={"X-Razorpay-Signature": "bad_sig"})
    assert res_bad_sig.status_code == 400

    import uuid
    uid = uuid.uuid4().hex[:8]
    event_id_unique = f"evt_wh_{uid}"

    # 4. Valid payment.captured event
    webhook_event = {
        "event_id": event_id_unique,
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_wh_captured_{uid}",
                    "order_id": "order_wh_1",
                    "amount": 499000,
                    "currency": "INR",
                    "status": "captured",
                    "method": "upi",
                    "notes": {"order_id": internal_id}
                }
            }
        }
    }
    raw_body = json.dumps(webhook_event).encode("utf-8")
    sig = compute_webhook_signature(raw_body)

    with patch("app.razorpay_service.is_razorpay_configured", return_value=True):
        res_wh = client.post(
            "/api/webhooks/razorpay",
            content=raw_body,
            headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"}
        )
        assert res_wh.status_code == 200
        assert res_wh.json()["status"] == "ok"

    # Order should now be marked Paid & Processing
    headers = get_auth_headers()
    order_doc = client.get(f"/api/orders/{internal_id}", headers=headers).json()
    assert order_doc["paymentStatus"] == "Paid"
    assert order_doc["status"] == "Processing"
    assert order_doc["razorpay_payment_id"] == f"pay_wh_captured_{uid}"

    # 5. Deduplication: Send identical event ID
    with patch("app.razorpay_service.is_razorpay_configured", return_value=True):
        res_dup = client.post(
            "/api/webhooks/razorpay",
            content=raw_body,
            headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"}
        )
        assert res_dup.status_code == 200
        assert "already processed" in res_dup.json()["message"].lower()

    # 6. Late payment.failed event must NOT downgrade Paid order
    failed_wh_event = {
        "event_id": f"evt_wh_fail_{uid}",
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_wh_failed_{uid}",
                    "order_id": "order_wh_1",
                    "notes": {"order_id": internal_id},
                    "error_code": "GATEWAY_TIMEOUT",
                    "error_description": "Late failure"
                }
            }
        }
    }

    raw_fail_body = json.dumps(failed_wh_event).encode("utf-8")
    sig_fail = compute_webhook_signature(raw_fail_body)

    with patch("app.razorpay_service.is_razorpay_configured", return_value=True):
        client.post(
            "/api/webhooks/razorpay",
            content=raw_fail_body,
            headers={"X-Razorpay-Signature": sig_fail, "Content-Type": "application/json"}
        )

    # Confirm order remained Paid
    order_doc_after = client.get(f"/api/orders/{internal_id}").json()
    assert order_doc_after["paymentStatus"] == "Paid"
