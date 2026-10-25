import html
import hmac
import hashlib
import json
import time
import asyncio
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

from app.main import app
from app.database import get_database, init_db
from app.config import RAZORPAY_WEBHOOK_SECRET, RAZORPAY_KEY_SECRET
from app.resend_service import (
    generate_order_email_content,
    get_product_url,
    get_resend_status,
    is_resend_configured,
    send_new_order_admin_notification,
    FRONTEND_BASE_URL,
    ADMIN_ORDERS_URL
)
from tests.conftest import TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD

def compute_webhook_signature(raw_body: bytes, secret: str = None) -> str:
    sec = secret or RAZORPAY_WEBHOOK_SECRET or RAZORPAY_KEY_SECRET or "test_secret_key"
    return hmac.new(sec.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

def compute_payment_signature(rzp_order_id: str, rzp_payment_id: str, secret: str = None) -> str:
    sec = secret or RAZORPAY_KEY_SECRET or "test_secret_key"
    msg = f"{rzp_order_id}|{rzp_payment_id}".encode("utf-8")
    return hmac.new(sec.encode("utf-8"), msg, hashlib.sha256).hexdigest()


client = TestClient(app)


@pytest.fixture(autouse=True)
def ensure_db_initialized():
    """Ensure in-memory mock database is connected for tests."""
    import asyncio
    asyncio.run(init_db())


# =========================================================================
# 1. Template Rendering & Content Generation Unit Tests
# =========================================================================

def test_generate_order_email_content_complete():
    order = {
        "id": "DBD-2026-9999",
        "customer": "Ayesha Khan",
        "email": "ayesha@example.com",
        "phone": "+91 98765 43210",
        "address": "Flat 12, Rose Garden, MG Road, Bangalore, Karnataka - 560038",
        "landmark": "Near Apollo Pharmacy, Indiranagar",
        "notes": "Please gift-wrap with a birthday note.",
        "date": "25 Oct 2026",
        "total": 8980.0,
        "subtotal": 8980.0,
        "discount": 0.0,
        "status": "Processing",
        "paymentMethod": "Cash on Delivery",
        "paymentStatus": "Pending",
        "items": [
            {
                "id": 1,
                "name": "Flower Pendant Necklace",
                "price": 4990.0,
                "qty": 1,
                "variant": "Champagne Gold",
                "img": "product_flower_necklace.jpg"
            },
            {
                "id": 2,
                "name": "Pearl Drop Earrings",
                "price": 3990.0,
                "qty": 1,
                "variant": "Gold",
                "img": "product_pearl_earrings.jpg"
            }
        ]
    }

    content = generate_order_email_content(order)

    # Subject
    assert content["subject"] == "New Order Received – Dazzle by Dua | Order #DBD-2026-9999"

    # HTML assertions
    html_body = content["html"]
    assert "Ayesha Khan" in html_body
    assert "ayesha@example.com" in html_body
    assert "+91 98765 43210" in html_body
    assert "Flat 12, Rose Garden, MG Road, Bangalore, Karnataka - 560038" in html_body
    assert "Near Apollo Pharmacy, Indiranagar" in html_body
    assert "Please gift-wrap with a birthday note." in html_body
    assert "Flower Pendant Necklace" in html_body
    assert "Pearl Drop Earrings" in html_body
    assert "PAYMENT PENDING" in html_body
    assert "Cash on Delivery" in html_body

    # Exact product links
    expected_product_url_1 = f"{FRONTEND_BASE_URL}/product-details.html?id=1"
    expected_product_url_2 = f"{FRONTEND_BASE_URL}/product-details.html?id=2"
    assert expected_product_url_1 in html_body
    assert expected_product_url_2 in html_body

    # Admin dashboard order link
    assert ADMIN_ORDERS_URL in html_body

    # Plain-text assertions
    text_body = content["text"]
    assert "DBD-2026-9999" in text_body
    assert "Ayesha Khan" in text_body
    assert "ayesha@example.com" in text_body
    assert "+91 98765 43210" in text_body
    assert "Near Apollo Pharmacy, Indiranagar" in text_body
    assert expected_product_url_1 in text_body
    assert expected_product_url_2 in text_body
    assert ADMIN_ORDERS_URL in text_body


def test_html_escaping_prevents_script_injection():
    malicious_order = {
        "id": "DBD-2026-0001",
        "customer": "<script>alert('pwned')</script>",
        "email": "hacker@test.com\" onmouseover=\"alert(1)",
        "phone": "<img src=x onerror=alert('xss')>",
        "address": "<b>Street</b> <iframe src='malicious.com'></iframe>",
        "notes": "<script>fetch('http://evil.com')</script>",
        "paymentMethod": "Cash on Delivery",
        "paymentStatus": "Pending",
        "total": 100.0,
        "items": [
            {
                "id": "<img src=x onerror=alert(2)>",
                "name": "<b onfocus=alert(3)>Gold Ring</b>",
                "price": 100.0,
                "qty": 1,
                "variant": "<script>evil()</script>"
            }
        ]
    }

    content = generate_order_email_content(malicious_order)
    html_body = content["html"]

    # Raw tags and unescaped script/iframe/img must NOT exist as HTML tags
    assert "<script>" not in html_body
    assert "<iframe" not in html_body
    assert "<img src=x" not in html_body

    # Must be safely escaped as entity text
    assert "&lt;script&gt;" in html_body
    assert "&lt;img src=x" in html_body
    assert "&lt;iframe" in html_body


def test_missing_optional_fields_handled_gracefully():
    minimal_order = {
        "id": "DBD-MINIMAL",
        "customer": "",
        "email": "",
        "phone": None,
        "address": None,
        "notes": None,
        "total": 0.0,
        "items": []
    }

    content = generate_order_email_content(minimal_order)
    assert content["subject"] == "New Order Received – Dazzle by Dua | Order #DBD-MINIMAL"
    assert "Valued Customer" in content["html"]
    assert "Not provided" in content["html"]
    assert "No items listed." in content["html"]


# =========================================================================
# 2. End-to-End API Integration & Lifecycle Tests
# =========================================================================

def test_cod_order_placement_triggers_resend_notification():
    with patch("resend.Emails.send") as mock_send, \
         patch("app.resend_service.RESEND_API_KEY", "re_test_key_12345"), \
         patch("app.resend_service.ADMIN_EMAIL", "owner@dazzlebydua.com"), \
         patch("app.resend_service.RESEND_FROM_EMAIL", "orders@dazzlebydua.com"):

        mock_send.return_value = {"id": "msg_resend_mock_cod_123"}

        payload = {
            "id": "DBD-COD-TEST-01",
            "customer": "Fatima Zahra",
            "email": "fatima@example.com",
            "phone": "+91 91234 56789",
            "address": "12 Lotus Lane, Bandra West, Mumbai - 400050",
            "total": 4990.0,
            "paymentMethod": "Cash on Delivery",
            "paymentStatus": "Pending",
            "notes": "Fragile jewellery, please handle with care.",
            "items": [
                {
                    "id": 1,
                    "name": "Flower Pendant Necklace",
                    "price": 4990.0,
                    "qty": 1,
                    "variant": "Champagne Gold"
                }
            ]
        }

        res = client.post("/api/orders", json=payload)
        assert res.status_code == 201
        order_data = res.json()
        assert order_data["id"] == "DBD-COD-TEST-01"

        # Verify Resend was invoked with correct parameters
        assert mock_send.call_count == 1
        call_args = mock_send.call_args[0][0]

        assert call_args["to"] == ["owner@dazzlebydua.com"]
        assert call_args["from"] == "orders@dazzlebydua.com"
        assert "Order #DBD-COD-TEST-01" in call_args["subject"]
        assert "Fatima Zahra" in call_args["html"]
        assert "Flower Pendant Necklace" in call_args["html"]
        assert "PAYMENT PENDING" in call_args["html"]
        assert "Cash on Delivery" in call_args["html"]
        assert "product-details.html?id=1" in call_args["html"]


def test_resend_failure_does_not_abort_order_creation():
    """If Resend API errors or times out, the customer order must still be successfully created."""
    with patch("resend.Emails.send") as mock_send, \
         patch("app.resend_service.RESEND_API_KEY", "re_test_key_12345"), \
         patch("app.resend_service.ADMIN_EMAIL", "owner@dazzlebydua.com"):

        mock_send.side_effect = Exception("Resend API rate limit or network timeout")

        payload = {
            "id": "DBD-FAILSAFE-01",
            "customer": "Priya Sharma",
            "email": "priya@example.com",
            "phone": "+91 99887 76655",
            "address": "45 Park Street, Kolkata - 700016",
            "total": 3990.0,
            "paymentMethod": "Cash on Delivery",
            "paymentStatus": "Pending",
            "items": [
                {
                    "id": 2,
                    "name": "Pearl Drop Earrings",
                    "price": 3990.0,
                    "qty": 1
                }
            ]
        }

        # Order creation must succeed with HTTP 201 despite Resend failure
        res = client.post("/api/orders", json=payload)
        assert res.status_code == 201
        assert res.json()["id"] == "DBD-FAILSAFE-01"

        # Check DB to verify order exists and error was recorded
        import asyncio
        async def _check():
            db = get_database()
            saved = await db.orders.find_one({"id": "DBD-FAILSAFE-01"})
            assert saved["notifications"].get("admin_new_order_sent") is not True
            assert "Resend API rate limit" in saved["notifications"]["admin_new_order_error"]

        asyncio.run(_check())


def test_idempotency_prevents_duplicate_notifications():
    """Verify that multiple notification dispatches for the same order do not send duplicate emails."""
    with patch("resend.Emails.send") as mock_send, \
         patch("app.resend_service.RESEND_API_KEY", "re_test_key_12345"), \
         patch("app.resend_service.ADMIN_EMAIL", "owner@dazzlebydua.com"):

        mock_send.return_value = {"id": "msg_resend_single_001"}

        order = {
            "id": "DBD-IDEM-01",
            "customer": "Neha Roy",
            "email": "neha@example.com",
            "total": 5990.0,
            "items": []
        }

        import asyncio
        async def _test():
            db = get_database()
            await db.orders.insert_one(dict(order))

            # First dispatch
            res1 = await send_new_order_admin_notification(order, db=db)
            assert res1["status"] == "sent"

            # Second duplicate dispatch (e.g. webhook retry)
            res2 = await send_new_order_admin_notification(order, db=db)
            assert res2["status"] == "skipped"
            assert res2["reason"] == "already_sent"

            # Resend must only be called once
            assert mock_send.call_count == 1

        asyncio.run(_test())


def test_diagnostic_status_masks_email_and_hides_secrets():
    with patch("app.resend_service.RESEND_API_KEY", "re_secret_key_1234567890"), \
         patch("app.resend_service.ADMIN_EMAIL", "manager@dazzlebydua.com"), \
         patch("app.resend_service.RESEND_FROM_EMAIL", "orders@dazzlebydua.com"):

        status = get_resend_status()
        assert status["configured"] is True
        assert status["from_email"] == "orders@dazzlebydua.com"
        assert "secret_key" not in str(status)
        assert status["admin_email"] == "m***@dazzlebydua.com"


# =========================================================================
# 3. Verification & Bug Fix Tests: Concurrency, Retries & Lifecycles
# =========================================================================

def test_notification_retry_after_failure_succeeds():
    """Verify that if Resend fails on the first attempt, the notification can be retried successfully without lockouts."""
    with patch("resend.Emails.send") as mock_send, \
         patch("app.resend_service.RESEND_API_KEY", "re_test_key_retry"), \
         patch("app.resend_service.ADMIN_EMAIL", "owner@dazzlebydua.com"):

        # 1. First attempt fails due to network glitch
        mock_send.side_effect = Exception("Temporary connection reset by peer")

        order = {
            "id": "DBD-RETRY-01",
            "customer": "Zainab Begum",
            "email": "zainab@example.com",
            "total": 3500.0,
            "items": []
        }

        async def _test_retry():
            db = get_database()
            await db.orders.insert_one(dict(order))

            # Attempt 1: Should fail safely and record error in DB
            res1 = await send_new_order_admin_notification(order, db=db)
            assert res1["status"] == "error"
            assert "Temporary connection reset" in res1["error"]

            # DB check: Pending must be cleared so retry is possible
            saved_after_fail = await db.orders.find_one({"id": "DBD-RETRY-01"})
            assert saved_after_fail["notifications"].get("admin_new_order_sent") is not True
            assert saved_after_fail["notifications"].get("admin_new_order_pending") is False
            assert "Temporary connection reset" in saved_after_fail["notifications"].get("admin_new_order_error", "")

            # Attempt 2: Resend service recovered
            mock_send.side_effect = None
            mock_send.return_value = {"id": "msg_resend_retry_success_999"}

            res2 = await send_new_order_admin_notification(order, db=db)
            assert res2["status"] == "sent"
            assert res2["resend_id"] == "msg_resend_retry_success_999"

            # DB check: Now successfully marked as sent
            saved_after_success = await db.orders.find_one({"id": "DBD-RETRY-01"})
            assert saved_after_success["notifications"].get("admin_new_order_sent") is True
            assert saved_after_success["notifications"].get("admin_new_order_id") == "msg_resend_retry_success_999"
            assert saved_after_success["notifications"].get("admin_new_order_pending") is False

        asyncio.run(_test_retry())


def test_simultaneous_notification_attempts_prevents_duplicate_sending():
    """Verify that simultaneous notification dispatches (e.g. verify + webhook race) only invoke Resend once."""
    with patch("resend.Emails.send") as mock_send, \
         patch("app.resend_service.RESEND_API_KEY", "re_test_key_concurrent"), \
         patch("app.resend_service.ADMIN_EMAIL", "owner@dazzlebydua.com"):

        def slow_send(params):
            time.sleep(0.05)
            return {"id": "msg_concurrent_001"}

        mock_send.side_effect = slow_send

        order = {
            "id": "DBD-CONCURRENT-01",
            "customer": "Siddharth Verma",
            "email": "sid@example.com",
            "total": 6500.0,
            "items": []
        }

        async def _test_concurrency():
            db = get_database()
            await db.orders.insert_one(dict(order))

            # Fire two simultaneous dispatches
            task1 = send_new_order_admin_notification(order, db=db)
            task2 = send_new_order_admin_notification(order, db=db)
            results = await asyncio.gather(task1, task2)

            statuses = [r["status"] for r in results]
            # Exactly one must have sent, and one must have skipped
            assert "sent" in statuses
            assert "skipped" in statuses

            skipped_res = next(r for r in results if r["status"] == "skipped")
            assert skipped_res["reason"] in ("already_sent", "already_sent_or_in_flight")

            # Resend API must only be invoked exactly once
            assert mock_send.call_count == 1

        asyncio.run(_test_concurrency())


def test_duplicate_razorpay_webhook_events_handled_idempotently():
    """Verify payment.captured followed by order.paid or duplicate webhooks trigger email only once."""
    with patch("resend.Emails.send") as mock_send, \
         patch("app.resend_service.RESEND_API_KEY", "re_test_key_webhook"), \
         patch("app.resend_service.ADMIN_EMAIL", "owner@dazzlebydua.com"), \
         patch("app.razorpay_service.is_razorpay_configured", return_value=True), \
         patch("app.razorpay_service.is_razorpay_webhook_configured", return_value=True):

        mock_send.return_value = {"id": "msg_webhook_first_001"}

        order_id = "DBD-WH-IDEM-01"
        rzp_order_id = "order_wh_idem_test"

        async def _setup_order():
            db = get_database()
            await db.orders.insert_one({
                "id": order_id,
                "customer": "Kavita Sen",
                "email": "kavita@example.com",
                "phone": "+91 98989 89898",
                "total": 5400.0,
                "status": "Payment Pending",
                "paymentMethod": "Razorpay Online",
                "paymentStatus": "Pending",
                "razorpay_order_id": rzp_order_id,
                "items": [{"id": 1, "name": "Gold Pendant", "price": 5400.0, "qty": 1}]
            })

        asyncio.run(_setup_order())

        # 1. First event: payment.captured (event_id: evt_cap_101)
        event_captured = {
            "event_id": "evt_cap_101",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_cap_101",
                        "order_id": rzp_order_id,
                        "amount": 540000,
                        "currency": "INR",
                        "status": "captured",
                        "method": "upi",
                        "notes": {"order_id": order_id}
                    }
                }
            }
        }
        body_captured = json.dumps(event_captured).encode("utf-8")
        sig_captured = compute_webhook_signature(body_captured)

        res_cap = client.post(
            "/api/webhooks/razorpay",
            content=body_captured,
            headers={"X-Razorpay-Signature": sig_captured, "Content-Type": "application/json"}
        )
        assert res_cap.status_code == 200
        assert mock_send.call_count == 1

        # 2. Second event: order.paid (event_id: evt_paid_102) for the exact same order
        event_order_paid = {
            "event_id": "evt_paid_102",
            "event": "order.paid",
            "payload": {
                "order": {
                    "entity": {
                        "id": rzp_order_id,
                        "amount_paid": 540000,
                        "currency": "INR",
                        "status": "paid",
                        "receipt": order_id,
                        "notes": {"order_id": order_id}
                    }
                },
                "payment": {
                    "entity": {
                        "id": "pay_cap_101",
                        "order_id": rzp_order_id,
                        "amount": 540000
                    }
                }
            }
        }
        body_order_paid = json.dumps(event_order_paid).encode("utf-8")
        sig_order_paid = compute_webhook_signature(body_order_paid)

        res_ord_paid = client.post(
            "/api/webhooks/razorpay",
            content=body_order_paid,
            headers={"X-Razorpay-Signature": sig_order_paid, "Content-Type": "application/json"}
        )
        assert res_ord_paid.status_code == 200
        # Call count must REMAIN 1 because the order is already Paid and notification was already dispatched
        assert mock_send.call_count == 1

        # 3. Third event: Duplicate delivery of exact same payment.captured event
        res_dup = client.post(
            "/api/webhooks/razorpay",
            content=body_captured,
            headers={"X-Razorpay-Signature": sig_captured, "Content-Type": "application/json"}
        )
        assert res_dup.status_code == 200
        assert res_dup.json()["message"] == "Event already processed"
        assert mock_send.call_count == 1


def test_accurate_payment_status_cod_vs_razorpay():
    """Verify COD is marked PAYMENT PENDING, unverified online orders cannot fake Paid, and verified orders show PAID."""
    with patch("resend.Emails.send") as mock_send, \
         patch("app.resend_service.RESEND_API_KEY", "re_test_key_status"), \
         patch("app.resend_service.ADMIN_EMAIL", "owner@dazzlebydua.com"), \
         patch("app.razorpay_service.is_razorpay_configured", return_value=True), \
         patch("app.razorpay_service.fetch_payment_details") as mock_fetch:

        mock_send.return_value = {"id": "msg_status_test_001"}

        # 1. COD Order: Must show "PAYMENT PENDING" and be saved with paymentStatus: "Pending"
        cod_payload = {
            "id": "DBD-COD-STATUS-01",
            "customer": "Ananya Roy",
            "email": "ananya@example.com",
            "total": 2990.0,
            "paymentMethod": "Cash on Delivery",
            "paymentStatus": "Pending",
            "items": [{"id": 1, "name": "Earrings", "price": 2990.0, "qty": 1}]
        }
        res_cod = client.post("/api/orders", json=cod_payload)
        assert res_cod.status_code == 201
        assert res_cod.json()["paymentStatus"] == "Pending"

        cod_call_args = mock_send.call_args[0][0]
        assert "PAYMENT PENDING" in cod_call_args["html"]
        assert "PAID & VERIFIED" not in cod_call_args["html"]

        # 2. Storefront attempt trying to inject "Paid" without signature: Must be forced to "Pending"
        fake_online_payload = {
            "id": "DBD-FAKE-ONLINE-01",
            "customer": "Unverified User",
            "email": "fake@example.com",
            "total": 4990.0,
            "paymentMethod": "Razorpay Online",
            "paymentStatus": "Paid",  # Attacker attempts to bypass payment
            "items": [{"id": 1, "name": "Earrings", "price": 4990.0, "qty": 1}]
        }
        res_fake = client.post("/api/orders", json=fake_online_payload)
        assert res_fake.status_code == 201
        assert res_fake.json()["paymentStatus"] == "Pending"

        fake_call_args = mock_send.call_args[0][0]
        assert "PAYMENT PENDING" in fake_call_args["html"]
        assert "PAID & VERIFIED" not in fake_call_args["html"]

        # 3. Cryptographically Verified Razorpay Order: Must show "PAID & VERIFIED"
        async def _setup_verified():
            db = get_database()
            await db.orders.insert_one({
                "id": "DBD-RZP-VERIFY-01",
                "customer": "Rohan Mehra",
                "email": "rohan@example.com",
                "total": 4990.0,
                "status": "Payment Pending",
                "paymentMethod": "Razorpay Online",
                "paymentStatus": "Pending",
                "razorpay_order_id": "order_rzp_ver_123",
                "items": [{"id": 1, "name": "Earrings", "price": 4990.0, "qty": 1}]
            })

        asyncio.run(_setup_verified())

        rzp_pay_id = "pay_rzp_ver_456"
        valid_sig = compute_payment_signature("order_rzp_ver_123", rzp_pay_id)
        mock_fetch.return_value = {
            "id": rzp_pay_id,
            "amount": 499000,
            "currency": "INR",
            "status": "captured",
            "method": "card"
        }

        verify_payload = {
            "order_id": "DBD-RZP-VERIFY-01",
            "razorpay_order_id": "order_rzp_ver_123",
            "razorpay_payment_id": rzp_pay_id,
            "razorpay_signature": valid_sig
        }
        res_ver = client.post("/api/orders/razorpay/verify", json=verify_payload)
        assert res_ver.status_code == 200
        assert res_ver.json()["order"]["paymentStatus"] == "Paid"

        ver_call_args = mock_send.call_args[0][0]
        assert "PAID & VERIFIED" in ver_call_args["html"]



def test_landmark_in_cod_order_and_resend_email():
    """Verify landmark is stored in MongoDB and transmitted in email notifications."""
    with patch("resend.Emails.send") as mock_send, \
         patch("app.resend_service.RESEND_API_KEY", "re_test_key_landmark"), \
         patch("app.resend_service.ADMIN_EMAIL", "owner@dazzlebydua.com"):

        mock_send.return_value = {"id": "msg_landmark_test_001"}

        order_payload = {
            "id": "DBD-LANDMARK-01",
            "customer": "Zainab Sheikh",
            "email": "zainab@example.com",
            "phone": "+91 98123 45678",
            "address": "Flat 301, Lakeview Tower, Indiranagar, Bangalore",
            "landmark": "Opposite Metro Pillar 142",
            "total": 4990.0,
            "paymentMethod": "Cash on Delivery",
            "paymentStatus": "Pending",
            "items": [{"id": 1, "name": "Flower Pendant Necklace", "price": 4990.0, "qty": 1}]
        }

        res = client.post("/api/orders", json=order_payload)
        assert res.status_code == 201
        order_data = res.json()
        assert order_data["landmark"] == "Opposite Metro Pillar 142"

        # Check DB record
        async def _check_db():
            db = get_database()
            saved = await db.orders.find_one({"id": "DBD-LANDMARK-01"})
            assert saved["landmark"] == "Opposite Metro Pillar 142"

        asyncio.run(_check_db())

        # Check email payload
        assert mock_send.call_count == 1
        call_args = mock_send.call_args[0][0]
        assert "Opposite Metro Pillar 142" in call_args["html"]
        assert "Opposite Metro Pillar 142" in call_args["text"]
        assert "Landmark:" in call_args["html"]
        assert "Landmark:" in call_args["text"]
