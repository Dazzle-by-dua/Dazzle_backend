import pytest
import time
from starlette.testclient import TestClient
from app.main import app
from app.database import db_manager, get_database
from app.security import (
    create_access_token,
    _compute_totp,
    generate_totp_secret,
    generate_recovery_codes,
    verify_and_consume_recovery_code
)

from app.rate_limiter import _in_memory_store

from tests.conftest import (
    TEST_ADMIN_USERNAME,
    TEST_ADMIN_PASSWORD,
    TEST_ADMIN_EMAIL,
    TEST_ADMIN_NAME
)

client = TestClient(app)

@pytest.fixture(scope="session", autouse=True)
def app_lifespan():
    with client:
        yield


@pytest.fixture(autouse=True)
def ensure_clean_rate_limits():
    """Ensure in-memory and database rate limit stores and cookies are clean before each test."""
    _in_memory_store.clear()
    client.cookies.clear()
    try:
        db = get_database()
        if db is not None:
            import asyncio
            asyncio.run(db.rate_limits.delete_many({}))
    except Exception:
        pass


def get_admin_token():
    res = client.post("/api/auth/login", json={
        "username": TEST_ADMIN_USERNAME,
        "password": TEST_ADMIN_PASSWORD
    })
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.json()["token"]


# ========================================================
# 1. Price Tampering & Product Integrity Tests
# ========================================================

def test_price_tampering_ignored_and_backend_price_enforced():
    """Verify backend calculates order total from database price, ignoring client manipulation."""
    tampered_items = [
        {"id": 1, "name": "Flower Necklace", "price": 0.01, "qty": 1}
    ]
    res = client.post("/api/orders", json={
        "customer": "Security Tester",
        "email": "sectest@example.com",
        "phone": "9876543210",
        "city": "Hyderabad",
        "state": "Telangana",
        "address": "Banjara Hills",
        "total": 0.01,  # Client attempts to pay 1 paisa
        "items": tampered_items
    })
    assert res.status_code == 201
    order = res.json()
    # Flower necklace price is 4990.0 + Hyderabad delivery 50.0 = 5040.0
    assert order["subtotal"] == 4990.0
    assert order["total"] == 5040.0
    assert order["items"][0]["price"] == 4990.0


def test_reject_unknown_product_id():
    """Unknown product ID must be rejected with 400 Bad Request."""
    res = client.post("/api/orders", json={
        "customer": "Security Tester",
        "email": "sectest@example.com",
        "phone": "9876543210",
        "city": "Hyderabad",
        "state": "Telangana",
        "address": "Banjara Hills",
        "total": 100.0,
        "items": [{"id": 999999, "name": "Fake Product", "price": 100.0, "qty": 1}]
    })
    assert res.status_code == 400
    assert "does not exist" in res.json()["detail"]


def test_reject_empty_order_items():
    """Empty cart / items payload must be rejected with 400 Bad Request."""
    res = client.post("/api/orders", json={
        "customer": "Security Tester",
        "email": "sectest@example.com",
        "phone": "9876543210",
        "city": "Hyderabad",
        "state": "Telangana",
        "address": "Banjara Hills",
        "total": 100.0,
        "items": []
    })
    assert res.status_code == 400
    assert "at least one item" in res.json()["detail"].lower() or "empty" in res.json()["detail"].lower()


# ========================================================
# 2. Production Database Fallback Prevention
# ========================================================

def test_production_db_fallback_prevents_silent_mock(monkeypatch):
    """In production mode, missing MONGODB_URI must raise RuntimeError immediately."""
    from app.database import DatabaseManager
    import app.database as db_mod

    monkeypatch.setattr(db_mod, "IS_PRODUCTION", True)
    monkeypatch.setattr(db_mod, "MONGODB_URI", "")

    prod_mgr = DatabaseManager()
    with pytest.raises(RuntimeError) as exc_info:
        prod_mgr.get_db()
    assert "CRITICAL" in str(exc_info.value)
    assert "production" in str(exc_info.value).lower()


# ========================================================
# 3. Admin Session Revocation via token_version
# ========================================================

def test_admin_session_revocation_on_logout():
    """Logging out increments token_version; previously issued JWT must be rejected."""
    token = get_admin_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Verify active session works
    res = client.get("/api/auth/me", headers=headers)
    assert res.status_code == 200

    # Logout to revoke the session
    res_logout = client.post("/api/auth/logout", headers=headers)
    assert res_logout.status_code == 200
    client.cookies.clear()

    # The old token must now be rejected
    res_after = client.get("/api/auth/me", headers=headers)
    assert res_after.status_code == 401
    assert "revoked" in res_after.json()["detail"].lower()


# ========================================================
# 4. Admin Two-Factor Authentication (TOTP + Recovery Codes)
# ========================================================

def test_admin_2fa_setup_and_verification_lifecycle():
    """Complete lifecycle: setup 2FA, verify TOTP, login with 2FA, use recovery code, disable."""
    token = get_admin_token()
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Setup 2FA
    res_setup = client.post("/api/auth/2fa/setup", headers=headers)
    assert res_setup.status_code == 200
    setup_data = res_setup.json()
    assert setup_data["success"] is True
    assert "secret" in setup_data
    assert "otpauth_url" in setup_data
    assert len(setup_data["recovery_codes"]) == 8

    secret = setup_data["secret"]
    recovery_code = setup_data["recovery_codes"][0]

    # 2. Verify with wrong code -> fails
    res_bad = client.post("/api/auth/2fa/verify-and-enable", headers=headers, json={"code": "000000"})
    assert res_bad.status_code == 400

    # 3. Verify with valid TOTP code
    current_step = int(time.time() // 30)
    valid_totp = _compute_totp(secret, current_step)
    res_enable = client.post("/api/auth/2fa/verify-and-enable", headers=headers, json={"code": valid_totp})
    assert res_enable.status_code == 200
    assert res_enable.json()["success"] is True

    # 4. Attempt login -> must require 2FA
    res_login = client.post("/api/auth/login", json={
        "username": TEST_ADMIN_USERNAME,
        "password": TEST_ADMIN_PASSWORD
    })
    assert res_login.status_code == 200
    login_data = res_login.json()
    assert login_data.get("requires_2fa") is True
    temp_token = login_data.get("temp_token")
    assert temp_token is not None

    # 5. Complete 2FA login using single-use recovery code
    res_2fa_login = client.post("/api/auth/login/2fa", json={
        "temp_token": temp_token,
        "code": recovery_code
    })
    assert res_2fa_login.status_code == 200
    assert res_2fa_login.json()["success"] is True
    assert "admin_token" in res_2fa_login.cookies

    # 6. Reusing the consumed recovery code must fail
    res_login_again = client.post("/api/auth/login", json={
        "username": TEST_ADMIN_USERNAME,
        "password": TEST_ADMIN_PASSWORD
    })
    temp_token_2 = res_login_again.json()["temp_token"]
    res_reuse = client.post("/api/auth/login/2fa", json={
        "temp_token": temp_token_2,
        "code": recovery_code
    })
    assert res_reuse.status_code == 401

    # 7. Disable 2FA
    new_admin_token = res_2fa_login.json()["token"]
    current_totp = _compute_totp(secret, int(time.time() // 30))
    res_disable = client.post("/api/auth/2fa/disable", headers={"Authorization": f"Bearer {new_admin_token}"}, json={
        "password": TEST_ADMIN_PASSWORD,
        "code": current_totp
    })
    assert res_disable.status_code == 200


# ========================================================
# 5. Order Security & Authorization Tests
# ========================================================

def test_order_payment_status_authorization():
    """Verify GET /{order_id}/payment-status requires authorization and blocks guessing."""
    # Create an order
    order_res = client.post("/api/orders", json={
        "customer": "Status Tester",
        "email": "status@example.com",
        "phone": "9876543210",
        "city": "Hyderabad",
        "state": "Telangana",
        "address": "Jubilee Hills",
        "total": 1349.0,
        "items": [{"id": 1, "qty": 1}]
    })
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]

    # Unauthenticated attempt to view payment status of order ID without rzp credential
    res_anon = client.get(f"/api/orders/{order_id}/payment-status")
    assert res_anon.status_code == 401

    # Admin access succeeds
    admin_token = get_admin_token()
    res_admin = client.get(f"/api/orders/{order_id}/payment-status", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_admin.status_code == 200
    assert res_admin.json()["id"] == order_id


def test_payment_failure_unauthorized_rejection():
    """Unauthorized callers cannot manipulate payment failure on another order."""
    # Create an order
    order_res = client.post("/api/orders", json={
        "customer": "Failure Tester",
        "email": "failtest@example.com",
        "phone": "9876543210",
        "city": "Hyderabad",
        "state": "Telangana",
        "address": "Jubilee Hills",
        "total": 1349.0,
        "items": [{"id": 1, "qty": 1}]
    })
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]

    # Unauthenticated failure report without matching Razorpay ID -> 403 Forbidden
    res_bad = client.post("/api/orders/razorpay/payment-failed", json={
        "order_id": order_id,
        "error_code": "BAD_REQUEST",
        "error_description": "Tampered failure"
    })
    assert res_bad.status_code == 403


# ========================================================
# 6. Security Headers Middleware Tests
# ========================================================

def test_security_headers_present():
    """Verify security headers are attached to every response."""
    res = client.get("/")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "camera=()" in res.headers.get("Permissions-Policy", "")


# ========================================================
# 7. Rate Limiter Tests
# ========================================================

def test_rate_limiter_exceed_limit_returns_429():
    """RateLimiter returns 429 when threshold exceeded."""
    import asyncio
    from fastapi import Request
    from app.rate_limiter import RateLimiter

    limiter = RateLimiter(max_requests=3, window_seconds=60, key_prefix="test_rl")

    # Create dummy request
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("192.168.1.100", 12345),
    }
    dummy_req = Request(scope)

    # First 3 requests succeed
    for _ in range(3):
        asyncio.run(limiter.check_request(dummy_req))

    # 4th request must raise HTTPException(429)
    with pytest.raises(Exception) as exc_info:
        asyncio.run(limiter.check_request(dummy_req))
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


# ========================================================
# 8. Phase 3 Security Tests: 2FA Enforcement, Role Validation, Order Hardening, CSRF & File Upload
# ========================================================

def test_2fa_temp_token_cannot_access_admin_endpoints():
    """Verify that an intermediate 2FA temp_token cannot be used to authenticate as admin."""
    # Create a token with purpose="admin_2fa_pending"
    temp_token = create_access_token({"sub": TEST_ADMIN_USERNAME, "purpose": "admin_2fa_pending"})
    
    # Attempting to access protected admin route with this temp token must return 401
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {temp_token}"})
    assert res.status_code == 401
    assert "Could not validate admin credentials" in res.json()["detail"]


def test_customer_token_rejected_on_admin_routes():
    """Verify customer role token cannot access admin endpoints."""
    customer_token = create_access_token({"sub": "cust_12345", "role": "customer"})
    
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {customer_token}"})
    assert res.status_code == 401
    assert "Could not validate admin credentials" in res.json()["detail"]


def test_create_order_hardcodes_processing_status_and_ignores_client_rzp_ids():
    """Verify that a customer cannot set order status to 'Delivered' or tamper with razorpay IDs on creation."""
    res = client.post("/api/orders", json={
        "customer": "Tamper Tester",
        "email": "tamper@example.com",
        "phone": "9876543210",
        "city": "Hyderabad",
        "state": "Telangana",
        "address": "Banjara Hills",
        "total": 1000.0,
        "status": "Delivered",
        "razorpay_order_id": "order_fake_bypass",
        "razorpay_payment_id": "pay_fake_bypass",
        "payment_status": "Paid",
        "items": [{"id": 1, "qty": 1}]
    })
    assert res.status_code == 201
    order = res.json()
    assert order["status"] == "Processing"
    assert order["paymentStatus"] == "Pending"
    assert order.get("razorpay_order_id") is None
    assert order.get("razorpay_payment_id") is None


def test_order_item_rejects_excessive_quantity():
    """Verify orders reject unreasonable or invalid quantities (e.g. > 100 or <= 0)."""
    res = client.post("/api/orders", json={
        "customer": "Bulk Spammer",
        "email": "bulk@example.com",
        "phone": "9876543210",
        "city": "Hyderabad",
        "state": "Telangana",
        "address": "Banjara Hills",
        "total": 1000.0,
        "items": [{"id": 1, "qty": 101}]
    })
    assert res.status_code == 400
    assert "must be a positive integer between 1 and 100" in res.json()["detail"]


def test_production_factory_reset_blocked(monkeypatch):
    """Verify that in production environments, /api/backup/reset is completely blocked."""
    import app.routers.backup as backup_module
    monkeypatch.setattr(backup_module, "IS_PRODUCTION", True)
    
    admin_token = get_admin_token()
    res = client.post("/api/backup/reset", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 403
    assert "strictly disabled in production" in res.json()["detail"]


def test_media_upload_rejects_non_image_and_oversized():
    """Verify media uploads reject non-image MIME types and enforce 10MB limit."""
    admin_token = get_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # 1. Non-image file
    res_bad_type = client.post(
        "/api/media/upload",
        files={"file": ("malicious.exe", b"MZ\x90\x00\x03\x00\x00\x00", "application/x-dosexec")},
        headers=headers
    )
    assert res_bad_type.status_code == 400
    assert "Only image files" in res_bad_type.json()["detail"]
    
    # 2. Oversized file (> 10MB)
    huge_data = b"x" * (10 * 1024 * 1024 + 100)
    res_huge = client.post(
        "/api/media/upload",
        files={"file": ("huge.png", huge_data, "image/png")},
        headers=headers
    )
    assert res_huge.status_code == 413
    assert "exceeds the 10 MB limit" in res_huge.json()["detail"]


def test_csrf_origin_verification_blocks_unauthorized_cookie_post():
    """Verify that requests carrying an auth cookie are blocked if Origin is unauthorized."""
    client.cookies.set("customer_token", "dummy_token_value")
    
    # Evil origin
    res_evil = client.post(
        "/api/orders",
        json={"customer": "CSRF Attack", "email": "test@example.com", "phone": "1234567890", "city": "Hyd", "state": "TS", "address": "Banjara", "total": 1000.0, "items": [{"id": 1, "qty": 1}]},
        headers={"Origin": "https://evil-attacker-site.com"}
    )
    assert res_evil.status_code == 403
    assert "Cross-Origin Request Blocked" in res_evil.json()["detail"]
    
    # Trusted origin
    res_trusted = client.post(
        "/api/orders",
        json={"customer": "CSRF Test", "email": "test@example.com", "phone": "1234567890", "city": "Hyd", "state": "TS", "address": "Banjara", "total": 1000.0, "items": [{"id": 1, "qty": 1}]},
        headers={"Origin": "https://dazzlebydua.com"}
    )
    # Should not be 403 (could be 201 or 401 depending on dummy token validation, but CSRF middleware allowed it)
    assert res_evil.status_code == 403
    assert res_trusted.status_code != 403
    client.cookies.clear()


def test_clean_doc_strips_all_sensitive_keys():
    """Verify that clean_doc strips all sensitive credentials and token hashes."""
    from app.database import clean_doc
    raw_doc = {
        "_id": "60d5ec49f1b2c8a1b8e4f1a1",
        "username": "admin",
        "password_hash": "$2b$12$secretpasswordhash",
        "two_factor": {"secret": "JBSWY3DPEHPK3PXP"},
        "two_factor_pending": {"secret": "TEST"},
        "otp_verifier": "hashed_otp_code",
        "signup_token_hash": "signup_hash",
        "reset_token_hash": "reset_hash",
        "email": "admin@dazzlebydua.com"
    }
    cleaned = clean_doc(raw_doc)
    assert "_id" not in cleaned
    assert "password_hash" not in cleaned
    assert "two_factor" not in cleaned
    assert "two_factor_pending" not in cleaned
    assert "otp_verifier" not in cleaned
    assert "signup_token_hash" not in cleaned
    assert "reset_token_hash" not in cleaned
    assert cleaned["username"] == "admin"
    assert cleaned["email"] == "admin@dazzlebydua.com"


# ========================================================
# 9. Additional Prioritized Security Tests: CSRF, File Uploads & Recursive Sanitization
# ========================================================

# --- CSRF Tests ---

def test_csrf_missing_origin_and_referer_blocked():
    """Cookie-authenticated mutation requests without Origin AND Referer must be rejected with 403."""
    client.cookies.set("customer_token", "dummy_cookie_session")
    res = client.post(
        "/api/orders",
        json={"customer": "Attacker With No Origin", "total": 100.0, "items": [{"id": 1, "qty": 1}]}
    )
    assert res.status_code == 403
    assert "Missing Origin and Referer" in res.json()["detail"]
    client.cookies.clear()


def test_csrf_malicious_origin_blocked():
    """Cookie-authenticated mutation requests with an untrusted Origin must be rejected with 403."""
    client.cookies.set("customer_token", "dummy_cookie_session")
    res = client.post(
        "/api/orders",
        json={"customer": "CSRF Attack", "total": 100.0, "items": [{"id": 1, "qty": 1}]},
        headers={"Origin": "https://malicious-phishing-site.com"}
    )
    assert res.status_code == 403
    assert "Unauthorized Origin" in res.json()["detail"]
    client.cookies.clear()


def test_csrf_valid_origin_allowed():
    """Cookie-authenticated mutation requests from configured production frontend origins are accepted."""
    client.cookies.set("customer_token", "dummy_cookie_session")
    # Valid origin 1: custom domain
    res1 = client.post(
        "/api/orders",
        json={"customer": "Legit Customer", "email": "legit@example.com", "city": "Hyderabad", "state": "Telangana", "address": "Banjara", "total": 1000.0, "items": [{"id": 1, "qty": 1}]},
        headers={"Origin": "https://dazzlebydua.com"}
    )
    assert res1.status_code != 403
    
    # Valid origin 2: GitHub Pages domain
    res2 = client.post(
        "/api/orders",
        json={"customer": "Legit Customer", "email": "legit@example.com", "city": "Hyderabad", "state": "Telangana", "address": "Banjara", "total": 1000.0, "items": [{"id": 1, "qty": 1}]},
        headers={"Origin": "https://dazzle-by-dua.github.io"}
    )
    assert res2.status_code != 403
    client.cookies.clear()


def test_csrf_valid_referer_allowed():
    """Cookie-authenticated requests with missing Origin but valid Referer are accepted."""
    client.cookies.set("customer_token", "dummy_cookie_session")
    res = client.post(
        "/api/orders",
        json={"customer": "Legit Referer", "email": "legit@example.com", "city": "Hyderabad", "state": "Telangana", "address": "Banjara", "total": 1000.0, "items": [{"id": 1, "qty": 1}]},
        headers={"Referer": "https://dazzlebydua.com/checkout.html"}
    )
    assert res.status_code != 403

    # Malicious referer is blocked
    res_bad_ref = client.post(
        "/api/orders",
        json={"customer": "Bad Referer", "total": 1000.0, "items": [{"id": 1, "qty": 1}]},
        headers={"Referer": "https://attacker.com/evil.html"}
    )
    assert res_bad_ref.status_code == 403
    assert "Unauthorized Referer" in res_bad_ref.json()["detail"]
    client.cookies.clear()


# --- File Upload Tests ---

def test_upload_rejects_spoofed_mime_type():
    """Uploads with image MIME type but non-image file signature (e.g. Windows executable) must be rejected."""
    admin_token = get_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Executable disguised as image/jpeg
    fake_jpeg = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
    res = client.post(
        "/api/media/upload",
        files={"file": ("fake_product.jpg", fake_jpeg, "image/jpeg")},
        headers=headers
    )
    assert res.status_code == 400
    assert "Invalid image contents" in res.json()["detail"]


def test_upload_rejects_svg_script_injection():
    """SVG files must be rejected to prevent Stored XSS and XML entity attacks."""
    admin_token = get_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    svg_payload = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert("XSS")</script></svg>'
    res = client.post(
        "/api/media/upload",
        files={"file": ("vector.svg", svg_payload, "image/svg+xml")},
        headers=headers
    )
    assert res.status_code == 400
    assert "SVG uploads are disabled for security reasons" in res.json()["detail"]


def test_upload_rejects_invalid_corrupted_contents():
    """Truncated or corrupted image files must be rejected."""
    admin_token = get_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    corrupt_bytes = b"corrupted"
    res = client.post(
        "/api/media/upload",
        files={"file": ("corrupt.png", corrupt_bytes, "image/png")},
        headers=headers
    )
    assert res.status_code == 400
    assert "Invalid image file" in res.json()["detail"]


def test_upload_valid_raster_image_succeeds():
    """Valid raster images (e.g. standard 1x1 GIF) must succeed with magic bytes verification."""
    admin_token = get_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Minimal 1x1 GIF byte stream that passes magic bytes verification
    gif_bytes = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    res = client.post(
        "/api/media/upload",
        files={"file": ("ring_sample.gif", gif_bytes, "image/gif")},
        headers=headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["mime_type"] == "image/gif"
    assert "ring_sample" in data["filename"]


# --- Recursive Document Sanitization Tests ---

def test_recursive_clean_doc_nested_dictionaries():
    """Verify clean_doc recursively removes sensitive fields in nested dictionaries."""
    from app.database import clean_doc
    nested_doc = {
        "id": 101,
        "username": "admin_dua",
        "email": "dua@dazzlebydua.com",
        "security": {
            "two_factor": {"secret": "TOTP_SECRET_123", "recovery_codes": ["code1", "code2"]},
            "two_factor_pending": {"secret": "PENDING_456"},
            "password_hash": "$2b$12$supersecurehash",
            "last_login": "2026-11-09T12:00:00Z"
        },
        "settings": {
            "notifications": True,
            "theme": "gold"
        }
    }
    cleaned = clean_doc(nested_doc)
    
    # Sensitive nested keys stripped
    assert "two_factor" not in cleaned["security"]
    assert "two_factor_pending" not in cleaned["security"]
    assert "password_hash" not in cleaned["security"]
    
    # Public nested keys preserved
    assert cleaned["id"] == 101
    assert cleaned["username"] == "admin_dua"
    assert cleaned["security"]["last_login"] == "2026-11-09T12:00:00Z"
    assert cleaned["settings"]["theme"] == "gold"


def test_recursive_clean_doc_inside_lists():
    """Verify clean_doc recursively sanitizes dictionaries contained inside lists."""
    from app.database import clean_doc
    doc_with_lists = {
        "order_id": "DBD-2026-9999",
        "customer": "Ayesha Khan",
        "audit_trail": [
            {
                "action": "otp_request",
                "otp_verifier": "$2b$12$hashed_otp_value",
                "timestamp": "2026-11-09T10:00:00Z"
            },
            {
                "action": "password_reset",
                "reset_token_hash": "sha256_reset_hash_value",
                "signup_token_hash": "sha256_signup_hash_value",
                "details": {
                    "password_hash": "$2b$12$old_pass_hash",
                    "status": "success"
                }
            }
        ],
        "items": [
            {"id": 1, "name": "Emerald Pendant", "price": 4990.0}
        ]
    }
    cleaned = clean_doc(doc_with_lists)
    
    # Inside first list element
    assert "otp_verifier" not in cleaned["audit_trail"][0]
    assert cleaned["audit_trail"][0]["action"] == "otp_request"
    assert cleaned["audit_trail"][0]["timestamp"] == "2026-11-09T10:00:00Z"
    
    # Inside second list element
    assert "reset_token_hash" not in cleaned["audit_trail"][1]
    assert "signup_token_hash" not in cleaned["audit_trail"][1]
    assert "password_hash" not in cleaned["audit_trail"][1]["details"]
    assert cleaned["audit_trail"][1]["details"]["status"] == "success"
    
    # Unrelated list preserved
    assert len(cleaned["items"]) == 1
    assert cleaned["items"][0]["name"] == "Emerald Pendant"
    assert cleaned["items"][0]["price"] == 4990.0


# ========================================================
# 10. Phase 3 Final Independent Security Audit Tests
# ========================================================

def test_csrf_origin_null_rejected():
    """Origin: null (e.g. from sandboxed iframes or local HTML files) must be rejected with 403."""
    client.cookies.set("customer_token", "dummy_token")
    res = client.post(
        "/api/orders",
        json={"customer": "Null Origin Test", "total": 100.0, "items": [{"id": 1, "qty": 1}]},
        headers={"Origin": "null"}
    )
    assert res.status_code == 403
    assert "Unauthorized Origin" in res.json()["detail"]
    client.cookies.clear()


def test_csrf_malformed_referer_rejected():
    """Malformed Referer headers (missing scheme, host, or invalid URL structure) must be rejected with 403."""
    client.cookies.set("customer_token", "dummy_token")
    res = client.post(
        "/api/orders",
        json={"customer": "Malformed Referer Test", "total": 100.0, "items": [{"id": 1, "qty": 1}]},
        headers={"Referer": "not-a-valid-scheme"}
    )
    assert res.status_code == 403
    assert "Malformed Referer" in res.json()["detail"]
    client.cookies.clear()


def test_upload_rejects_oversized_dimensions():
    """Images exceeding maximum dimension limits (e.g. >5000px) must be rejected before processing."""
    from PIL import Image
    import io

    admin_token = get_admin_token()
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Create an image that is 5001 x 100 px (exceeds width limit of 5000px)
    img = Image.new("RGB", (5001, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    oversized_bytes = buf.getvalue()

    res = client.post(
        "/api/media/upload",
        files={"file": ("wide_banner.jpg", oversized_bytes, "image/jpeg")},
        headers=headers
    )
    assert res.status_code == 400
    assert "dimensions exceed maximum allowed limit" in res.json()["detail"]


def test_recursive_clean_doc_product_variants_and_customer_data():
    """Verify clean_doc preserves nested public MongoDB IDs and legitimate fields on catalog & customer records."""
    from app.database import clean_doc
    from bson import ObjectId

    raw_product = {
        "_id": ObjectId(),
        "id": 42,
        "name": "Diamond Solitaire Ring",
        "price": 14999.0,
        "category": "Rings",
        "variants": [
            {
                "_id": ObjectId(),
                "id": "v-18k-gold",
                "title": "18K Yellow Gold",
                "sku": "DBD-RNG-18K",
                "price": 14999.0,
                "stock": 5
            },
            {
                "_id": ObjectId(),
                "id": "v-platinum",
                "title": "Platinum 950",
                "sku": "DBD-RNG-PLT",
                "price": 18999.0,
                "stock": 3
            }
        ],
        "metadata": {
            "internal_secret_hash": "$2b$12$do_not_leak",
            "password_hash": "$2b$12$internal_hash",
            "tags": ["diamond", "solitaire", "luxury"]
        }
    }

    cleaned = clean_doc(raw_product)

    # 1. Internal MongoDB ObjectIds and sensitive keys removed
    assert "_id" not in cleaned
    assert "password_hash" not in cleaned["metadata"]
    assert "_id" not in cleaned["variants"][0]
    assert "_id" not in cleaned["variants"][1]

    # 2. Legitimate public IDs, nested variants, and arrays preserved intact
    assert cleaned["id"] == 42
    assert cleaned["name"] == "Diamond Solitaire Ring"
    assert len(cleaned["variants"]) == 2
    assert cleaned["variants"][0]["id"] == "v-18k-gold"
    assert cleaned["variants"][0]["sku"] == "DBD-RNG-18K"
    assert cleaned["variants"][1]["id"] == "v-platinum"
    assert cleaned["variants"][1]["price"] == 18999.0
    assert cleaned["metadata"]["tags"] == ["diamond", "solitaire", "luxury"]


def test_admin_token_rejected_on_customer_endpoints():
    """Verify admin role token cannot access protected customer routes."""
    admin_token = get_admin_token()
    res = client.get("/api/customer/orders", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 401
    assert "Could not validate customer credentials" in res.json()["detail"]


def test_expired_token_rejected():
    """Verify expired JWT tokens are immediately rejected with 401."""
    import datetime
    expired_token = create_access_token(
        {"sub": TEST_ADMIN_USERNAME},
        expires_delta=datetime.timedelta(seconds=-60)
    )
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert res.status_code == 401
    assert "Could not validate admin credentials" in res.json()["detail"]


def test_admin_endpoints_enforce_server_side_authorization():
    """Admin mutation endpoints reject unauthenticated callers with 401."""
    client.cookies.clear()
    res = client.post("/api/products", json={"name": "Unauthorized Product", "price": 1000.0})
    assert res.status_code == 401



