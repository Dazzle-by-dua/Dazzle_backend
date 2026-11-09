import re
import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends, Response, Request
from app.config import IS_PRODUCTION
from app.database import get_database
from app.rate_limiter import RateLimiter
from app.security import (
    verify_password,
    create_access_token,
    decode_access_token,
    get_current_admin,
    get_current_admin_optional,
    generate_totp_secret,
    get_totp_uri,
    verify_totp_code,
    generate_recovery_codes,
    verify_and_consume_recovery_code,
)
from app.models.schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminProfile,
    Admin2FASetupResponse,
    Admin2FAVerifyRequest,
    Admin2FALoginRequest,
    Admin2FADisableRequest,
)

router = APIRouter(prefix="/api/auth", tags=["Admin Authentication"])

admin_login_limiter = RateLimiter(max_requests=5, window_seconds=900, key_prefix="admin_login")
admin_2fa_limiter = RateLimiter(max_requests=5, window_seconds=900, key_prefix="admin_2fa")


def set_admin_cookie(response: Response, token: str, days: int = 1):
    """Set secure, HttpOnly session cookie for admin authentication."""
    samesite_policy = "none" if IS_PRODUCTION else "lax"
    response.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite=samesite_policy,
        max_age=days * 86400,
        path="/"
    )


def clear_admin_cookie(response: Response):
    """Cleanly delete admin session cookie."""
    samesite_policy = "none" if IS_PRODUCTION else "lax"
    response.delete_cookie(
        key="admin_token",
        path="/",
        secure=IS_PRODUCTION,
        samesite=samesite_policy
    )


@router.post("/login", response_model=AdminLoginResponse)
async def login(payload: AdminLoginRequest, response: Response, request: Request):
    await admin_login_limiter.check_request(request)

    clean_id = payload.username.strip().lower()
    clean_pass = payload.password.strip()
    db = get_database()

    escaped_id = re.escape(clean_id)
    admin = await db.admins.find_one({"$or": [
        {"username": {"$regex": f"^{escaped_id}$", "$options": "i"}},
        {"email": {"$regex": f"^{escaped_id}$", "$options": "i"}}
    ]})

    if not admin or not verify_password(clean_pass, admin.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials. Please check your username/email and password."
        )

    # Reset any rate limit on valid credentials
    await admin_login_limiter.reset_request(request)

    # Check if Two-Factor Authentication (2FA) is enabled for this admin
    two_factor = admin.get("two_factor", {})
    if two_factor.get("enabled", False):
        temp_token = create_access_token(
            data={"sub": admin["username"], "purpose": "admin_2fa_pending"},
            expires_delta=datetime.timedelta(minutes=5)
        )
        return {
            "success": True,
            "requires_2fa": True,
            "temp_token": temp_token,
            "message": "Two-factor authentication code required."
        }

    days = 7 if payload.rememberMe else 1
    token_expires = datetime.timedelta(days=days)
    token_version = int(admin.get("token_version", 1))
    if admin.get("token_version") is None:
        await db.admins.update_one({"username": admin["username"]}, {"$set": {"token_version": 1}})

    token = create_access_token(
        data={
            "sub": admin["username"],
            "email": admin["email"],
            "role": admin["role"],
            "token_version": token_version
        },
        expires_delta=token_expires
    )

    set_admin_cookie(response, token, days=days)

    return {
        "success": True,
        "user": {
            "user": admin["name"],
            "email": admin["email"],
            "role": admin["role"]
        },
        "token": token,
        "loginTime": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }


@router.post("/login/2fa", response_model=AdminLoginResponse)
async def login_2fa(payload: Admin2FALoginRequest, response: Response, request: Request):
    await admin_2fa_limiter.check_request(request)

    decoded = decode_access_token(payload.temp_token)
    if not decoded or decoded.get("purpose") != "admin_2fa_pending":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Verification session has expired. Please log in again."
        )

    username = decoded.get("sub")
    db = get_database()
    admin = await db.admins.find_one({"username": username})
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin account not found."
        )

    two_factor = admin.get("two_factor", {})
    secret = two_factor.get("secret", "")
    code = payload.code.strip()

    is_valid = False
    # Check standard 6-digit TOTP
    if verify_totp_code(secret, code):
        is_valid = True
    else:
        # Check single-use backup/recovery codes
        stored_recovery_hashes = two_factor.get("recovery_codes", [])
        code_matched, updated_hashes = verify_and_consume_recovery_code(code, stored_recovery_hashes)
        if code_matched:
            is_valid = True
            await db.admins.update_one(
                {"username": username},
                {"$set": {"two_factor.recovery_codes": updated_hashes}}
            )

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication code or recovery code. Please try again."
        )

    # Successful 2FA verification: reset limiter and issue admin cookie
    await admin_2fa_limiter.reset_request(request)

    token_expires = datetime.timedelta(days=1)
    token_version = int(admin.get("token_version", 1))

    token = create_access_token(
        data={
            "sub": admin["username"],
            "email": admin["email"],
            "role": admin["role"],
            "token_version": token_version
        },
        expires_delta=token_expires
    )

    set_admin_cookie(response, token, days=1)

    return {
        "success": True,
        "user": {
            "user": admin["name"],
            "email": admin["email"],
            "role": admin["role"]
        },
        "token": token,
        "loginTime": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }


@router.post("/2fa/setup", response_model=Admin2FASetupResponse)
async def setup_2fa(current_admin: dict = Depends(get_current_admin)):
    """
    Generate a new TOTP secret key, otpauth URI, and 8 one-time recovery codes
    for enrollment into an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, etc.).
    """
    secret = generate_totp_secret()
    username = current_admin["username"]
    otpauth_url = get_totp_uri(username=username, secret=secret)
    plain_codes, hashed_codes = generate_recovery_codes(count=8)

    db = get_database()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Store pending setup configuration
    await db.admins.update_one(
        {"username": username},
        {
            "$set": {
                "two_factor_pending": {
                    "secret": secret,
                    "recovery_codes": hashed_codes,
                    "created_at": now_iso
                }
            }
        }
    )

    return {
        "success": True,
        "secret": secret,
        "otpauth_url": otpauth_url,
        "recovery_codes": plain_codes,
        "message": "Scan the QR code or enter the secret key into your authenticator app, then confirm with a 6-digit code."
    }


@router.post("/2fa/verify-and-enable")
async def verify_and_enable_2fa(
    payload: Admin2FAVerifyRequest,
    current_admin: dict = Depends(get_current_admin)
):
    """Confirm 6-digit TOTP code and activate Two-Factor Authentication."""
    username = current_admin["username"]
    db = get_database()
    admin = await db.admins.find_one({"username": username})
    if not admin:
        raise HTTPException(status_code=404, detail="Admin account not found.")

    pending = admin.get("two_factor_pending")
    if not pending or not pending.get("secret"):
        raise HTTPException(
            status_code=400,
            detail="No pending 2FA enrollment found. Please initiate setup first."
        )

    if not verify_totp_code(pending["secret"], payload.code):
        raise HTTPException(
            status_code=400,
            detail="Invalid 6-digit verification code. Please check your authenticator app and try again."
        )

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    await db.admins.update_one(
        {"username": username},
        {
            "$set": {
                "two_factor": {
                    "enabled": True,
                    "secret": pending["secret"],
                    "recovery_codes": pending.get("recovery_codes", []),
                    "enabled_at": now_iso
                }
            },
            "$unset": {"two_factor_pending": ""}
        }
    )

    return {
        "success": True,
        "message": "Two-factor authentication has been enabled successfully."
    }


@router.post("/2fa/disable")
async def disable_2fa(
    payload: Admin2FADisableRequest,
    current_admin: dict = Depends(get_current_admin)
):
    """Disable Two-Factor Authentication with current password and TOTP confirmation."""
    username = current_admin["username"]
    db = get_database()
    admin = await db.admins.find_one({"username": username})
    if not admin:
        raise HTTPException(status_code=404, detail="Admin account not found.")

    if not verify_password(payload.password, admin.get("password_hash", "")):
        raise HTTPException(
            status_code=400,
            detail="Incorrect password. Cannot disable two-factor authentication."
        )

    two_factor = admin.get("two_factor", {})
    if not two_factor.get("enabled", False):
        return {"success": True, "message": "Two-factor authentication is already disabled."}

    secret = two_factor.get("secret", "")
    if not verify_totp_code(secret, payload.code):
        raise HTTPException(
            status_code=400,
            detail="Invalid 6-digit verification code. Cannot disable two-factor authentication."
        )

    await db.admins.update_one(
        {"username": username},
        {
            "$set": {"two_factor": {"enabled": False}},
            "$unset": {"two_factor_pending": ""}
        }
    )

    return {
        "success": True,
        "message": "Two-factor authentication has been disabled."
    }


@router.get("/me", response_model=AdminProfile)
async def get_current_admin_profile(current_admin: dict = Depends(get_current_admin)):
    return {
        "user": current_admin["name"],
        "email": current_admin["email"],
        "role": current_admin["role"]
    }


@router.post("/logout")
async def logout(
    response: Response,
    current_admin: Optional[dict] = Depends(get_current_admin_optional)
):
    # Invalidate session in database by incrementing token_version
    if current_admin:
        db = get_database()
        current_ver = int(current_admin.get("token_version", 1))
        await db.admins.update_one(
            {"username": current_admin["username"]},
            {"$set": {"token_version": current_ver + 1}}
        )

    clear_admin_cookie(response)
    return {"success": True, "message": "Logged out successfully."}
