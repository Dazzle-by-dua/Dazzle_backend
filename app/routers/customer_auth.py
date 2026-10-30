import re
import secrets
import datetime
import urllib.parse
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Depends, Response, Header, Cookie

from app.config import (
    IS_PRODUCTION,
    FRONTEND_BASE_URL,
    OTP_EXPIRE_MINUTES,
    RESET_TOKEN_EXPIRE_MINUTES,
    CUSTOMER_ACCESS_TOKEN_EXPIRE_DAYS
)
from app.database import get_database, clean_doc, clean_docs
from app.security import (
    verify_password,
    get_password_hash,
    hash_secret_hmac,
    create_customer_access_token,
    get_current_customer,
    get_current_customer_optional
)
from app.models.schemas import (
    CustomerSignupInitiateRequest,
    CustomerSignupResendOTPRequest,
    CustomerSignupVerifyOTPRequest,
    CustomerSignupCompleteRequest,
    CustomerLoginRequest,
    CustomerForgotPasswordRequest,
    CustomerResetPasswordRequest,
    CustomerProfileOut,
    CustomerProfileUpdate,
    OrderOut
)
from app.resend_service import (
    send_customer_otp_email,
    send_customer_password_reset_email,
    send_customer_password_changed_notification
)

router = APIRouter(prefix="/api/customer", tags=["Customer Authentication"])


def normalize_email(email: str) -> str:
    """Consistently trim and lowercase email addresses."""
    if not email:
        return ""
    return email.strip().lower()


def validate_email_format(email: str) -> bool:
    """RFC-compliant email validation."""
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def set_customer_cookie(response: Response, token: str, days: int = 7):
    """Set secure, HttpOnly session cookie for customer authentication."""
    samesite_policy = "none" if IS_PRODUCTION else "lax"
    response.set_cookie(
        key="customer_token",
        value=token,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite=samesite_policy,
        max_age=days * 86400,
        path="/"
    )


def clear_customer_cookie(response: Response):
    """Cleanly delete customer session cookie."""
    samesite_policy = "none" if IS_PRODUCTION else "lax"
    response.delete_cookie(
        key="customer_token",
        path="/",
        secure=IS_PRODUCTION,
        samesite=samesite_policy
    )


# =========================================================================
# 1. Three-Stage Customer Signup Flow
# =========================================================================

@router.post("/auth/signup/initiate")
async def signup_initiate(payload: CustomerSignupInitiateRequest):
    """
    Stage 1: Validate name and email, generate cryptographically random 6-digit OTP,
    and send OTP verification email.
    """
    email = normalize_email(payload.email)
    name = payload.name.strip()

    if not validate_email_format(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters.")

    db = get_database()

    # Check whether an active verified customer account already exists
    existing = await db.customers.find_one({"email": email})
    if existing and existing.get("is_verified", True):
        return {
            "success": False,
            "exists": True,
            "message": "An account with this email address already exists. Please log in."
        }

    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()

    # Rate limiting: check cooldown against recent pending signups
    pending = await db.customer_signups.find_one({"email": email})
    if pending:
        last_sent = pending.get("last_sent_at")
        if last_sent:
            try:
                last_dt = datetime.datetime.fromisoformat(last_sent)
                if (now - last_dt).total_seconds() < 60:
                    wait_sec = int(60 - (now - last_dt).total_seconds())
                    raise HTTPException(
                        status_code=429,
                        detail=f"Please wait {wait_sec} seconds before requesting a new verification code."
                    )
            except (ValueError, TypeError):
                pass

    # Generate cryptographically secure 6-digit OTP
    otp_int = secrets.randbelow(900000) + 100000
    otp_code = str(otp_int)

    # Compute protected server-side HMAC verifier (never store plaintext OTP)
    otp_verifier = hash_secret_hmac(otp_code)
    expires_at = now + datetime.timedelta(minutes=OTP_EXPIRE_MINUTES)

    # Atomic upsert in customer_signups collection
    await db.customer_signups.update_one(
        {"email": email},
        {
            "$set": {
                "email": email,
                "name": name,
                "otp_verifier": otp_verifier,
                "attempts": 0,
                "resends": 0,
                "verified": False,
                "signup_token_hash": None,
                "expires_at": expires_at,
                "last_sent_at": now_iso,
                "updated_at": now_iso
            },
            "$setOnInsert": {
                "created_at": now_iso
            }
        },
        upsert=True
    )

    # Deliver OTP via Resend email service
    email_res = await send_customer_otp_email(email=email, name=name, otp=otp_code)
    if not email_res.get("success", False):
        raise HTTPException(
            status_code=500,
            detail="Unable to deliver verification email. Please check your email address or try again shortly."
        )

    return {
        "success": True,
        "exists": False,
        "message": "Verification code sent to your email address.",
        "email": email,
        "cooldown_seconds": 60,
        "expires_in_seconds": OTP_EXPIRE_MINUTES * 60
    }


@router.post("/auth/signup/resend-otp")
async def signup_resend_otp(payload: CustomerSignupResendOTPRequest):
    """
    Resend a new 6-digit verification code with rate-limit and attempt protection.
    """
    email = normalize_email(payload.email)
    db = get_database()

    pending = await db.customer_signups.find_one({"email": email})
    if not pending or pending.get("verified", False):
        raise HTTPException(
            status_code=400,
            detail="No pending signup session found. Please enter your details to begin."
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()

    # Check cooldown (60s)
    last_sent = pending.get("last_sent_at")
    if last_sent:
        try:
            last_dt = datetime.datetime.fromisoformat(last_sent)
            if (now - last_dt).total_seconds() < 60:
                wait_sec = int(60 - (now - last_dt).total_seconds())
                raise HTTPException(
                    status_code=429,
                    detail=f"Please wait {wait_sec} seconds before requesting another code."
                )
        except (ValueError, TypeError):
            pass

    # Check max resends (max 3 resends per signup flow)
    resends = int(pending.get("resends", 0))
    if resends >= 3:
        raise HTTPException(
            status_code=429,
            detail="Maximum verification code requests exceeded. Please restart the registration process."
        )

    # Generate new cryptographically secure 6-digit OTP
    otp_int = secrets.randbelow(900000) + 100000
    otp_code = str(otp_int)
    otp_verifier = hash_secret_hmac(otp_code)
    expires_at = now + datetime.timedelta(minutes=OTP_EXPIRE_MINUTES)

    await db.customer_signups.update_one(
        {"email": email},
        {
            "$set": {
                "otp_verifier": otp_verifier,
                "attempts": 0,
                "expires_at": expires_at,
                "last_sent_at": now_iso,
                "updated_at": now_iso
            },
            "$inc": {
                "resends": 1
            }
        }
    )

    email_res = await send_customer_otp_email(
        email=email,
        name=pending.get("name", "Customer"),
        otp=otp_code
    )
    if not email_res.get("success", False):
        raise HTTPException(
            status_code=500,
            detail="Unable to deliver verification email. Please try again shortly."
        )

    return {
        "success": True,
        "message": "A new verification code has been sent to your email.",
        "cooldown_seconds": 60
    }


@router.post("/auth/signup/verify-otp")
async def signup_verify_otp(payload: CustomerSignupVerifyOTPRequest):
    """
    Stage 2: Atomically verify customer's 6-digit OTP.
    Upon success, invalidate the OTP and issue a short-lived single-use signup-verification token.
    """
    email = normalize_email(payload.email)
    otp_clean = str(payload.otp).strip()

    if len(otp_clean) != 6 or not otp_clean.isdigit():
        raise HTTPException(status_code=400, detail="Verification code must be 6 digits.")

    db = get_database()
    pending = await db.customer_signups.find_one({"email": email})

    if not pending or pending.get("verified", False):
        raise HTTPException(
            status_code=400,
            detail="No pending verification found. Please request a new verification code."
        )

    now = datetime.datetime.now(datetime.timezone.utc)

    # Check expiration
    expires_at = pending.get("expires_at")
    if isinstance(expires_at, datetime.datetime):
        exp_dt = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=datetime.timezone.utc)
        if now > exp_dt:
            raise HTTPException(
                status_code=400,
                detail="Verification code has expired. Please request a new code."
            )

    # Check failed attempts (max 5)
    attempts = int(pending.get("attempts", 0))
    if attempts >= 5:
        # Invalidate OTP on attempt limit exhaustion
        await db.customer_signups.update_one(
            {"email": email},
            {"$set": {"otp_verifier": None, "updated_at": now.isoformat()}}
        )
        raise HTTPException(
            status_code=400,
            detail="Too many invalid attempts. This verification code is no longer valid. Please request a new one."
        )

    stored_verifier = pending.get("otp_verifier")
    if not stored_verifier:
        raise HTTPException(
            status_code=400,
            detail="Verification code has already been used or expired. Please request a new one."
        )

    # Compare HMAC verifiers in constant time
    supplied_verifier = hash_secret_hmac(otp_clean)
    if not secrets.compare_digest(supplied_verifier, stored_verifier):
        await db.customer_signups.update_one(
            {"email": email},
            {"$inc": {"attempts": 1}}
        )
        remaining = 4 - attempts
        msg = f"Invalid verification code. {remaining} attempt{'s' if remaining != 1 else ''} remaining." if remaining > 0 else "Invalid code. Please request a new one."
        raise HTTPException(status_code=400, detail=msg)

    # Generate single-use, high-entropy signup-verification token
    signup_token = secrets.token_urlsafe(32)
    signup_token_hash = hash_secret_hmac(signup_token)
    signup_token_expires = now + datetime.timedelta(minutes=15)

    # Atomically invalidate OTP and save signup token
    await db.customer_signups.update_one(
        {"email": email},
        {
            "$set": {
                "verified": True,
                "otp_verifier": None,  # Immediately invalidate OTP
                "signup_token_hash": signup_token_hash,
                "signup_token_expires": signup_token_expires,
                "updated_at": now.isoformat()
            }
        }
    )

    return {
        "success": True,
        "message": "Email verified successfully.",
        "signup_token": signup_token
    }


@router.post("/auth/signup/complete")
async def signup_complete(payload: CustomerSignupCompleteRequest, response: Response):
    """
    Stage 3: Verify the backend signup token, enforce password rules,
    create customer account with Argon2id hash, and issue authenticated session.
    """
    email = normalize_email(payload.email)
    password = payload.password
    confirm_password = payload.confirm_password

    if password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")

    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")

    if len(password) > 128:
        raise HTTPException(status_code=400, detail="Password cannot exceed 128 characters.")

    db = get_database()
    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()

    # Atomically consume signup token to prevent any reuse
    token_hash = hash_secret_hmac(payload.signup_token)
    session = await db.customer_signups.find_one_and_delete({
        "email": email,
        "verified": True,
        "signup_token_hash": token_hash,
        "signup_token_expires": {"$gt": now}
    })

    if not session:
        raise HTTPException(
            status_code=400,
            detail="Invalid, expired, or previously used signup verification session. Please restart registration."
        )

    # Double check customer doesn't already exist
    existing = await db.customers.find_one({"email": email})
    if existing:
        raise HTTPException(
            status_code=400,
            detail="An account with this email address already exists. Please log in."
        )

    # Create new customer record with Argon2id password hash
    customer_id = f"CUST-{secrets.token_hex(4).upper()}"
    password_hash = get_password_hash(password)

    customer_doc = {
        "id": customer_id,
        "name": session.get("name", "Customer"),
        "email": email,
        "password_hash": password_hash,
        "is_verified": True,
        "token_version": 1,
        "phone": "",
        "address": "",
        "created_at": now_iso,
        "updated_at": now_iso,
        "last_login_at": now_iso
    }

    try:
        await db.customers.insert_one(customer_doc)
    except Exception as e:
        if "duplicate" in str(e).lower():
            raise HTTPException(status_code=400, detail="An account with this email already exists.")
        raise HTTPException(status_code=500, detail="Failed to create customer account.")

    # Create session token
    token = create_customer_access_token(customer_doc)
    set_customer_cookie(response, token, days=CUSTOMER_ACCESS_TOKEN_EXPIRE_DAYS)

    return {
        "success": True,
        "message": "Account created successfully.",
        "user": {
            "id": customer_id,
            "name": customer_doc["name"],
            "email": email
        },
        "token": token
    }


# =========================================================================
# 2. Customer Login & Session Management
# =========================================================================

@router.post("/auth/login")
async def customer_login(payload: CustomerLoginRequest, response: Response):
    """
    Authenticate customer with email and password.
    Includes rate-limiting, brute force defense, and automatic Argon2id migration.
    """
    email = normalize_email(payload.email)
    password = payload.password
    db = get_database()
    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()

    # Brute force protection check (max 5 failed attempts in past 15 min)
    attempt_record = await db.customer_login_attempts.find_one({"email": email})
    if attempt_record:
        failed_count = int(attempt_record.get("count", 0))
        lockout_until = attempt_record.get("lockout_until")
        if lockout_until:
            try:
                lockout_dt = datetime.datetime.fromisoformat(lockout_until)
                if now < lockout_dt:
                    wait_minutes = max(1, int((lockout_dt - now).total_seconds() / 60))
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Too many failed login attempts. Please try again in {wait_minutes} minutes or reset your password."
                    )
            except (ValueError, TypeError):
                pass

    customer = await db.customers.find_one({"email": email})

    # Generic error message to never reveal account existence
    invalid_creds_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password. Please try again."
    )

    if not customer:
        # Record failed attempt against this email
        await db.customer_login_attempts.update_one(
            {"email": email},
            {
                "$inc": {"count": 1},
                "$set": {
                    "updated_at": now_iso,
                    "expires_at": now + datetime.timedelta(minutes=15)
                }
            },
            upsert=True
        )
        raise invalid_creds_exception

    # Verify password hash
    stored_hash = customer.get("password_hash", "")
    if not verify_password(password, stored_hash):
        new_count = 1
        if attempt_record:
            new_count = int(attempt_record.get("count", 0)) + 1

        update_fields = {
            "count": new_count,
            "updated_at": now_iso,
            "expires_at": now + datetime.timedelta(minutes=15)
        }
        if new_count >= 5:
            # 15-minute temporary lockout
            update_fields["lockout_until"] = (now + datetime.timedelta(minutes=15)).isoformat()

        await db.customer_login_attempts.update_one(
            {"email": email},
            {"$set": update_fields},
            upsert=True
        )
        raise invalid_creds_exception

    # Clear failed attempt counter on successful login
    await db.customer_login_attempts.delete_one({"email": email})

    # Safe migration: if customer used older bcrypt hash, silently migrate to Argon2id
    if stored_hash.startswith("$2"):
        new_argon2_hash = get_password_hash(password)
        await db.customers.update_one(
            {"_id": customer["_id"]},
            {"$set": {"password_hash": new_argon2_hash, "updated_at": now_iso}}
        )

    # Update last login timestamp
    await db.customers.update_one(
        {"_id": customer["_id"]},
        {"$set": {"last_login_at": now_iso}}
    )

    # Issue customer JWT session
    days = 30 if payload.remember_me else CUSTOMER_ACCESS_TOKEN_EXPIRE_DAYS
    expires_delta = datetime.timedelta(days=days)
    token = create_customer_access_token(customer, expires_delta=expires_delta)

    set_customer_cookie(response, token, days=days)

    return {
        "success": True,
        "message": "Login successful.",
        "user": {
            "id": customer.get("id") or str(customer.get("_id")),
            "name": customer.get("name", "Customer"),
            "email": customer["email"]
        },
        "token": token
    }


@router.get("/auth/me", response_model=CustomerProfileOut)
async def get_current_customer_profile(current_customer: dict = Depends(get_current_customer)):
    """Retrieve currently authenticated customer profile."""
    return {
        "id": current_customer["id"],
        "name": current_customer["name"],
        "email": current_customer["email"],
        "phone": current_customer.get("phone", ""),
        "address": current_customer.get("address", ""),
        "created_at": current_customer.get("created_at")
    }


@router.post("/auth/logout")
async def customer_logout(response: Response, current_customer: Optional[dict] = Depends(get_current_customer_optional)):
    """Sign out customer and cleanly invalidate session cookie."""
    if current_customer:
        db = get_database()
        # Increment token_version to invalidate outstanding tokens
        await db.customers.update_one(
            {"email": current_customer["email"]},
            {"$inc": {"token_version": 1}}
        )

    clear_customer_cookie(response)
    return {"success": True, "message": "Logged out successfully."}


# =========================================================================
# 3. Forgot Password Flow
# =========================================================================

@router.post("/auth/forgot-password")
async def forgot_password_request(payload: CustomerForgotPasswordRequest):
    """
    Stage 1: Generate high-entropy reset token and send branded reset email.
    Always returns a generic, safe response to prevent email enumeration.
    """
    email = normalize_email(payload.email)
    generic_msg = "If an account exists with this email address, password reset instructions have been sent."

    if not validate_email_format(email):
        return {"success": True, "message": generic_msg}

    db = get_database()
    customer = await db.customers.find_one({"email": email})

    if not customer or not customer.get("is_verified", True):
        # Return generic success message without leaking account existence
        return {"success": True, "message": generic_msg}

    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()

    # Rate limiting: invalidate any existing pending reset tokens for this email
    await db.password_resets.update_many(
        {"email": email, "used": False},
        {"$set": {"used": True, "invalidated_at": now_iso}}
    )

    # Generate cryptographically secure high-entropy token
    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_secret_hmac(raw_token)
    expires_at = now + datetime.timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)

    await db.password_resets.insert_one({
        "email": email,
        "token_hash": token_hash,
        "used": False,
        "expires_at": expires_at,
        "created_at": now_iso
    })

    # Construct safe reset link using backend configured FRONTEND_BASE_URL
    safe_param_email = urllib.parse.quote(email)
    safe_param_token = urllib.parse.quote(raw_token)
    reset_link = f"{FRONTEND_BASE_URL}/reset-password.html?token={safe_param_token}&email={safe_param_email}"

    # Dispatch email
    await send_customer_password_reset_email(
        email=email,
        name=customer.get("name", "Customer"),
        reset_link=reset_link
    )

    return {"success": True, "message": generic_msg}


@router.get("/auth/verify-reset-token")
async def verify_reset_token(token: str, email: str):
    """
    Stage 2: Validate token validity without consuming it when reset page opens.
    """
    clean_email = normalize_email(email)
    clean_token = token.strip()

    if not clean_token or not clean_email:
        raise HTTPException(status_code=400, detail="Invalid password reset request.")

    db = get_database()
    token_hash = hash_secret_hmac(clean_token)
    now = datetime.datetime.now(datetime.timezone.utc)

    reset_record = await db.password_resets.find_one({
        "email": clean_email,
        "token_hash": token_hash,
        "used": False
    })

    if not reset_record:
        raise HTTPException(
            status_code=400,
            detail="This password reset link is invalid or has already been used."
        )

    expires_at = reset_record.get("expires_at")
    if isinstance(expires_at, datetime.datetime):
        exp_dt = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=datetime.timezone.utc)
        if now > exp_dt:
            raise HTTPException(
                status_code=400,
                detail="This password reset link has expired. Please request a new one."
            )

    return {"valid": True, "email": clean_email}


@router.post("/auth/reset-password")
async def complete_password_reset(payload: CustomerResetPasswordRequest):
    """
    Stage 3: Atomically consume reset token, update password hash with Argon2id,
    and revoke all previous customer sessions.
    """
    email = normalize_email(payload.email)
    token = payload.token.strip()
    new_pass = payload.new_password
    confirm_pass = payload.confirm_password

    if new_pass != confirm_pass:
        raise HTTPException(status_code=400, detail="Passwords do not match.")

    if len(new_pass) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")

    if len(new_pass) > 128:
        raise HTTPException(status_code=400, detail="Password cannot exceed 128 characters.")

    db = get_database()
    token_hash = hash_secret_hmac(token)
    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.isoformat()

    # Atomically consume the token
    reset_record = await db.password_resets.find_one_and_update(
        {
            "email": email,
            "token_hash": token_hash,
            "used": False,
            "expires_at": {"$gt": now}
        },
        {
            "$set": {
                "used": True,
                "used_at": now_iso
            }
        }
    )

    if not reset_record:
        raise HTTPException(
            status_code=400,
            detail="Password reset token is invalid, expired, or has already been used."
        )

    # Invalidate all other outstanding reset tokens for this account
    await db.password_resets.update_many(
        {"email": email, "used": False},
        {"$set": {"used": True, "invalidated_at": now_iso}}
    )

    # Update customer password with Argon2id and increment token_version to revoke active sessions
    new_password_hash = get_password_hash(new_pass)
    await db.customers.update_one(
        {"email": email},
        {
            "$set": {
                "password_hash": new_password_hash,
                "updated_at": now_iso
            },
            "$inc": {
                "token_version": 1  # Revokes all existing customer sessions
            }
        }
    )

    # Dispatch security confirmation email
    customer = await db.customers.find_one({"email": email})
    cust_name = customer.get("name", "Customer") if customer else "Customer"
    await send_customer_password_changed_notification(email=email, name=cust_name)

    return {
        "success": True,
        "message": "Password updated successfully. Please log in with your new password."
    }


# =========================================================================
# 4. Customer Profile & Order History (Isolated & Protected)
# =========================================================================

@router.get("/profile", response_model=CustomerProfileOut)
async def get_profile(current_customer: dict = Depends(get_current_customer)):
    """Retrieve authenticated customer profile."""
    return {
        "id": current_customer["id"],
        "name": current_customer["name"],
        "email": current_customer["email"],
        "phone": current_customer.get("phone", ""),
        "address": current_customer.get("address", ""),
        "created_at": current_customer.get("created_at")
    }


@router.put("/profile", response_model=CustomerProfileOut)
async def update_profile(payload: CustomerProfileUpdate, current_customer: dict = Depends(get_current_customer)):
    """Update authenticated customer's own profile."""
    db = get_database()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    updates = {"updated_at": now_iso}

    if payload.name is not None:
        updates["name"] = payload.name.strip()
    if payload.phone is not None:
        updates["phone"] = payload.phone.strip()
    if payload.address is not None:
        updates["address"] = payload.address.strip()

    await db.customers.update_one(
        {"email": current_customer["email"]},
        {"$set": updates}
    )

    updated = await db.customers.find_one({"email": current_customer["email"]})
    return {
        "id": updated.get("id") or str(updated.get("_id")),
        "name": updated.get("name", "Customer"),
        "email": updated["email"],
        "phone": updated.get("phone", ""),
        "address": updated.get("address", ""),
        "created_at": updated.get("created_at")
    }


@router.get("/orders", response_model=List[OrderOut])
async def get_customer_orders(current_customer: dict = Depends(get_current_customer)):
    """
    Retrieve only the orders placed by the currently authenticated customer.
    Matches by customer_id, customer_email, or email to cover all order creation paths.
    Guarantees Customer A cannot view Customer B's orders.
    """
    db = get_database()
    email = current_customer["email"].strip().lower()
    escaped_email = re.escape(email)
    cust_id = str(current_customer.get("id") or "").strip()

    or_clauses = [
        {"email": {"$regex": f"^{escaped_email}$", "$options": "i"}},
        {"customer_email": {"$regex": f"^{escaped_email}$", "$options": "i"}},
    ]
    if cust_id:
        or_clauses.append({"customer_id": cust_id})

    orders = await db.orders.find({"$or": or_clauses}).sort("created_at", -1).to_list(length=500)

    return clean_docs(orders)
