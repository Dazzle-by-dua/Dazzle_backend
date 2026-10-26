import re
import pytest
import urllib.parse
from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient

from app.main import app
from app.security import (
    get_password_hash,
    verify_password
)
from app.database import get_database

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def app_lifespan():
    with client:
        yield


# =========================================================================
# 1. Three-Stage Signup Lifecycle Tests
# =========================================================================

def test_signup_stage1_initiate_and_email_delivery():
    with patch("app.routers.customer_auth.send_customer_otp_email", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True, "id": "otp_test_1"}

        res = client.post("/api/customer/auth/signup/initiate", json={
            "name": "Dua Fatima",
            "email": "  DUA.FATIMA@example.com  "
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["exists"] is False
        assert data["email"] == "dua.fatima@example.com"
        assert "otp" not in data  # Never expose OTP in response

        mock_send.assert_awaited_once()
        call_kwargs = mock_send.await_args.kwargs
        assert call_kwargs["email"] == "dua.fatima@example.com"
        assert call_kwargs["name"] == "Dua Fatima"
        assert len(call_kwargs["otp"]) == 6
        assert call_kwargs["otp"].isdigit()


def test_signup_stage2_otp_verification_and_invalidation():
    email = "stage2.tester@example.com"

    # Step 1: Initiate signup and capture OTP
    with patch("app.routers.customer_auth.send_customer_otp_email", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True, "id": "otp_test_2"}
        res_init = client.post("/api/customer/auth/signup/initiate", json={
            "name": "Stage Two User",
            "email": email
        })
        assert res_init.status_code == 200
        otp = mock_send.await_args.kwargs["otp"]

    # Step 2: Try invalid OTP
    res_bad = client.post("/api/customer/auth/signup/verify-otp", json={
        "email": email,
        "otp": "000000"
    })
    assert res_bad.status_code == 400
    assert "invalid verification code" in res_bad.json()["detail"].lower()

    # Step 3: Supply correct OTP
    res_good = client.post("/api/customer/auth/signup/verify-otp", json={
        "email": email,
        "otp": otp
    })
    assert res_good.status_code == 200
    data = res_good.json()
    assert data["success"] is True
    assert "signup_token" in data
    signup_token = data["signup_token"]

    # Step 4: OTP reuse must be rejected
    res_reused = client.post("/api/customer/auth/signup/verify-otp", json={
        "email": email,
        "otp": otp
    })
    assert res_reused.status_code == 400


def test_signup_resend_cooldown():
    email = "resend.cooldown@example.com"

    # Initiate
    with patch("app.routers.customer_auth.send_customer_otp_email", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True, "id": "otp_test_3"}
        client.post("/api/customer/auth/signup/initiate", json={
            "name": "Cooldown Tester",
            "email": email
        })

    # Resending immediately must be rejected with 429 cooldown
    res_cooldown = client.post("/api/customer/auth/signup/resend-otp", json={"email": email})
    assert res_cooldown.status_code == 429
    assert "wait" in res_cooldown.json()["detail"].lower()


def test_signup_stage3_password_creation_and_token_invalidation():
    email = "stage3.complete@example.com"

    # Stage 1: Initiate
    with patch("app.routers.customer_auth.send_customer_otp_email", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True, "id": "otp_test_4"}
        client.post("/api/customer/auth/signup/initiate", json={
            "name": "Amina Khan",
            "email": email
        })
        otp = mock_send.await_args.kwargs["otp"]

    # Stage 2: Verify OTP
    res_verify = client.post("/api/customer/auth/signup/verify-otp", json={
        "email": email,
        "otp": otp
    })
    assert res_verify.status_code == 200
    signup_token = res_verify.json()["signup_token"]

    # Stage 3: Password mismatch validation
    res_mismatch = client.post("/api/customer/auth/signup/complete", json={
        "email": email,
        "signup_token": signup_token,
        "password": "SecurePassword123!",
        "confirm_password": "DifferentPassword123!"
    })
    assert res_mismatch.status_code == 400
    assert "match" in res_mismatch.json()["detail"].lower()

    # Stage 3: Password too short (< 8 characters)
    res_short = client.post("/api/customer/auth/signup/complete", json={
        "email": email,
        "signup_token": signup_token,
        "password": "Pass1!",
        "confirm_password": "Pass1!"
    })
    assert res_short.status_code in (400, 422)

    # Stage 3: Valid completion
    res_complete = client.post("/api/customer/auth/signup/complete", json={
        "email": email,
        "signup_token": signup_token,
        "password": "LuxuryPassword2026!#",
        "confirm_password": "LuxuryPassword2026!#"
    })
    assert res_complete.status_code == 200
    data = res_complete.json()
    assert data["success"] is True
    assert "token" in data
    assert data["user"]["email"] == email
    # Check customer cookie was set
    assert "customer_token" in res_complete.cookies

    # Reusing signup token must be rejected
    res_reuse = client.post("/api/customer/auth/signup/complete", json={
        "email": email,
        "signup_token": signup_token,
        "password": "LuxuryPassword2026!#",
        "confirm_password": "LuxuryPassword2026!#"
    })
    assert res_reuse.status_code == 400


def test_duplicate_signup_detected():
    email = "duplicate.test@example.com"

    # Register first account
    with patch("app.routers.customer_auth.send_customer_otp_email", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True, "id": "otp_test_5"}
        client.post("/api/customer/auth/signup/initiate", json={"name": "First User", "email": email})
        otp = mock_send.await_args.kwargs["otp"]

    res_v = client.post("/api/customer/auth/signup/verify-otp", json={"email": email, "otp": otp})
    token = res_v.json()["signup_token"]
    client.post("/api/customer/auth/signup/complete", json={
        "email": email,
        "signup_token": token,
        "password": "MasterPassword123!",
        "confirm_password": "MasterPassword123!"
    })

    # Second signup attempt with same email must detect existing account
    res_dup = client.post("/api/customer/auth/signup/initiate", json={"name": "Second User", "email": email})
    assert res_dup.status_code == 200
    dup_data = res_dup.json()
    assert dup_data["success"] is False
    assert dup_data["exists"] is True
    assert "already exists" in dup_data["message"].lower()


# =========================================================================
# 2. Password Hashing & Migration Tests
# =========================================================================

def test_argon2id_hashing():
    raw_pass = "DazzleFineJewellery2026!@"
    h = get_password_hash(raw_pass)
    assert h.startswith("$argon2id$")
    assert verify_password(raw_pass, h) is True
    assert verify_password("WrongPassword123!", h) is False


@pytest.mark.anyio
async def test_legacy_bcrypt_migration():
    import bcrypt
    db = get_database()
    email = "legacy.customer@example.com"
    raw_pass = "LegacyBcryptPassword123!"
    bcrypt_hash = bcrypt.hashpw(raw_pass.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    now_iso = "2026-01-01T00:00:00"

    await db.customers.insert_one({
        "id": "CUST-BCRYPT-1",
        "name": "Bcrypt Customer",
        "email": email,
        "password_hash": bcrypt_hash,
        "is_verified": True,
        "token_version": 1,
        "created_at": now_iso,
        "updated_at": now_iso
    })

    # Login with legacy password
    res = client.post("/api/customer/auth/login", json={
        "email": email,
        "password": raw_pass
    })
    assert res.status_code == 200

    # Verify database record automatically upgraded to Argon2id
    updated = await db.customers.find_one({"email": email})
    assert updated["password_hash"].startswith("$argon2id$")
    assert verify_password(raw_pass, updated["password_hash"]) is True


# =========================================================================
# 3. Customer Login, Logout & Session Management Tests
# =========================================================================

def test_customer_login_and_logout():
    email = "login.customer@example.com"
    pwd = "ValidCustomerPass1234!"

    # Create account
    with patch("app.routers.customer_auth.send_customer_otp_email", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True, "id": "otp_test_6"}
        client.post("/api/customer/auth/signup/initiate", json={"name": "Login User", "email": email})
        otp = mock_send.await_args.kwargs["otp"]

    res_v = client.post("/api/customer/auth/signup/verify-otp", json={"email": email, "otp": otp})
    token = res_v.json()["signup_token"]
    client.post("/api/customer/auth/signup/complete", json={
        "email": email,
        "signup_token": token,
        "password": pwd,
        "confirm_password": pwd
    })

    # 1. Invalid password
    res_bad = client.post("/api/customer/auth/login", json={"email": email, "password": "WrongPassword!"})
    assert res_bad.status_code == 401
    assert "invalid email or password" in res_bad.json()["detail"].lower()

    # 2. Unknown email
    res_unknown = client.post("/api/customer/auth/login", json={"email": "nobody@example.com", "password": pwd})
    assert res_unknown.status_code == 401
    assert "invalid email or password" in res_unknown.json()["detail"].lower()

    # 3. Valid login
    res_ok = client.post("/api/customer/auth/login", json={"email": email, "password": pwd, "remember_me": True})
    assert res_ok.status_code == 200
    login_data = res_ok.json()
    assert login_data["success"] is True
    jwt_token = login_data["token"]

    # 4. Access /api/customer/auth/me
    res_me = client.get("/api/customer/auth/me", headers={"Authorization": f"Bearer {jwt_token}"})
    assert res_me.status_code == 200
    assert res_me.json()["email"] == email

    # 5. Logout
    res_logout = client.post("/api/customer/auth/logout", headers={"Authorization": f"Bearer {jwt_token}"})
    assert res_logout.status_code == 200

    # 6. Verify revoked session cannot access /api/customer/auth/me
    res_revoked = client.get("/api/customer/auth/me", headers={"Authorization": f"Bearer {jwt_token}"})
    assert res_revoked.status_code == 401


# =========================================================================
# 4. Forgot Password Flow Tests
# =========================================================================

def test_forgot_password_and_reset_lifecycle():
    email = "forgot.tester@example.com"
    old_pass = "OriginalPassword123!"
    new_pass = "BrandNewPassword1234!"

    # Create account
    with patch("app.routers.customer_auth.send_customer_otp_email", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"success": True, "id": "otp_test_7"}
        client.post("/api/customer/auth/signup/initiate", json={"name": "Forgot User", "email": email})
        otp = mock_send.await_args.kwargs["otp"]

    res_v = client.post("/api/customer/auth/signup/verify-otp", json={"email": email, "otp": otp})
    token = res_v.json()["signup_token"]
    client.post("/api/customer/auth/signup/complete", json={
        "email": email,
        "signup_token": token,
        "password": old_pass,
        "confirm_password": old_pass
    })

    # Step 1: Request reset link
    with patch("app.routers.customer_auth.send_customer_password_reset_email", new_callable=AsyncMock) as mock_reset:
        mock_reset.return_value = {"success": True, "id": "reset_test_1"}
        res_forgot = client.post("/api/customer/auth/forgot-password", json={"email": email})
        assert res_forgot.status_code == 200
        assert "instructions have been sent" in res_forgot.json()["message"]

        mock_reset.assert_awaited_once()
        reset_link = mock_reset.await_args.kwargs["reset_link"]
        assert "reset-password.html?token=" in reset_link
        match = re.search(r"token=([^&]+)", reset_link)
        raw_reset_token = urllib.parse.unquote(match.group(1))

    # Step 2: Non-existent account returns identical generic message
    res_ghost = client.post("/api/customer/auth/forgot-password", json={"email": "ghost@example.com"})
    assert res_ghost.status_code == 200
    assert "instructions have been sent" in res_ghost.json()["message"]

    # Step 3: Validate token
    res_val = client.get(f"/api/customer/auth/verify-reset-token?token={raw_reset_token}&email={email}")
    assert res_val.status_code == 200
    assert res_val.json()["valid"] is True

    # Step 4: Complete reset
    with patch("app.routers.customer_auth.send_customer_password_changed_notification", new_callable=AsyncMock) as mock_notify:
        mock_notify.return_value = {"success": True}
        res_reset = client.post("/api/customer/auth/reset-password", json={
            "token": raw_reset_token,
            "email": email,
            "new_password": new_pass,
            "confirm_password": new_pass
        })
        assert res_reset.status_code == 200
        mock_notify.assert_awaited_once()

    # Step 5: Old password fails; new password succeeds
    res_old = client.post("/api/customer/auth/login", json={"email": email, "password": old_pass})
    assert res_old.status_code == 401

    res_new = client.post("/api/customer/auth/login", json={"email": email, "password": new_pass})
    assert res_new.status_code == 200

    # Step 6: Reusing reset token fails
    res_reuse = client.post("/api/customer/auth/reset-password", json={
        "token": raw_reset_token,
        "email": email,
        "new_password": "EvenNewerPass123!",
        "confirm_password": "EvenNewerPass123!"
    })
    assert res_reuse.status_code == 400


# =========================================================================
# 5. Order Isolation & Authorization Tests
# =========================================================================

@pytest.mark.anyio
async def test_customer_order_isolation():
    db = get_database()
    email_a = "alice@example.com"
    email_b = "bob@example.com"

    # Create Alice & Bob accounts via API
    for name, email in [("Alice", email_a), ("Bob", email_b)]:
        with patch("app.routers.customer_auth.send_customer_otp_email", new_callable=AsyncMock) as mock_s:
            mock_s.return_value = {"success": True}
            client.post("/api/customer/auth/signup/initiate", json={"name": name, "email": email})
            otp = mock_s.await_args.kwargs["otp"]
        res_v = client.post("/api/customer/auth/signup/verify-otp", json={"email": email, "otp": otp})
        token = res_v.json()["signup_token"]
        client.post("/api/customer/auth/signup/complete", json={
            "email": email,
            "signup_token": token,
            "password": "Password1234567!",
            "confirm_password": "Password1234567!"
        })

    # Login Alice & Bob to get valid customer tokens
    res_la = client.post("/api/customer/auth/login", json={"email": email_a, "password": "Password1234567!"})
    token_a = res_la.json()["token"]

    res_lb = client.post("/api/customer/auth/login", json={"email": email_b, "password": "Password1234567!"})
    token_b = res_lb.json()["token"]

    # Insert orders into MongoDB with valid OrderOut fields
    now_iso = "2026-10-26T12:00:00"
    await db.orders.insert_one({
        "id": "DBD-2026-7001",
        "customer": "Alice",
        "email": email_a,
        "total": 4990.0,
        "date": "26 Oct 2026",
        "status": "Processing",
        "paymentMethod": "UPI",
        "created_at": now_iso
    })
    await db.orders.insert_one({
        "id": "DBD-2026-7002",
        "customer": "Bob",
        "email": email_b,
        "total": 7990.0,
        "date": "26 Oct 2026",
        "status": "Delivered",
        "paymentMethod": "Razorpay Online",
        "created_at": now_iso
    })

    # 1. Alice sees only her own order
    res_a_orders = client.get("/api/customer/orders", headers={"Authorization": f"Bearer {token_a}"})
    assert res_a_orders.status_code == 200
    orders_a = res_a_orders.json()
    assert len(orders_a) == 1
    assert orders_a[0]["id"] == "DBD-2026-7001"

    # 2. Alice tries to view Bob's order directly -> 403 Forbidden
    res_forbidden = client.get("/api/orders/DBD-2026-7002", headers={"Authorization": f"Bearer {token_a}"})
    assert res_forbidden.status_code == 403

    # 3. Bob can view his own order
    res_bob_order = client.get("/api/orders/DBD-2026-7002", headers={"Authorization": f"Bearer {token_b}"})
    assert res_bob_order.status_code == 200
    assert res_bob_order.json()["id"] == "DBD-2026-7002"

    # 4. Unauthenticated access is rejected with 401
    unauth_client = TestClient(app)
    res_unauth = unauth_client.get("/api/orders/DBD-2026-7001")
    assert res_unauth.status_code == 401
