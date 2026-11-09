import hmac
import hashlib
import datetime
import base64
import struct
import time
import secrets
import urllib.parse
from typing import Optional
from fastapi import Depends, HTTPException, status, Header, Cookie
from jose import JWTError, jwt
import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from app.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, CUSTOMER_ACCESS_TOKEN_EXPIRE_DAYS

# RFC 9106 recommended Argon2id parameters
_argon2_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # 64 MB
    parallelism=1,
    hash_len=32,
    salt_len=16
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Safely verify a password against its stored hash.
    Supports Argon2id hashes, with automatic fallback verification for legacy bcrypt hashes.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        if hashed_password.startswith("$argon2"):
            try:
                return _argon2_hasher.verify(hashed_password, plain_password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False
        elif hashed_password.startswith("$2"):
            # Legacy bcrypt verification
            return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
        else:
            return False
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    """Hash password using Argon2id with unique cryptographically random salt."""
    return _argon2_hasher.hash(password)

def hash_secret_hmac(value: str) -> str:
    """Generate server-side HMAC-SHA256 verifier for OTPs and tokens."""
    return hmac.new(SECRET_KEY.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()

def generate_totp_secret() -> str:
    """Generate a random 32-character base32-encoded secret for TOTP (RFC 6238)."""
    random_bytes = secrets.token_bytes(20)
    return base64.b32encode(random_bytes).decode("ascii").replace("=", "")

def get_totp_uri(username: str, secret: str, issuer: str = "Dazzle by Dua") -> str:
    """Generate otpauth URI for standard authenticator app enrollment."""
    safe_user = urllib.parse.quote(username)
    safe_issuer = urllib.parse.quote(issuer)
    return f"otpauth://totp/{safe_issuer}:{safe_user}?secret={secret}&issuer={safe_issuer}&algorithm=SHA1&digits=6&period=30"

def _compute_totp(secret: str, time_step: int) -> str:
    """Compute 6-digit TOTP code for a given 30-second time step."""
    secret_clean = secret.strip().replace(" ", "").upper()
    pad_len = (8 - len(secret_clean) % 8) % 8
    key = base64.b32decode(secret_clean + "=" * pad_len, casefold=True)
    msg = struct.pack(">Q", time_step)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{code_int % 1000000:06d}"

def verify_totp_code(secret: str, code: str, window: int = 1) -> bool:
    """
    Verify RFC 6238 TOTP 6-digit code.
    Checks current step and +/- window steps for clock drift.
    """
    if not secret or not code:
        return False
    code_clean = str(code).strip().replace(" ", "")
    if len(code_clean) != 6 or not code_clean.isdigit():
        return False

    current_step = int(time.time() // 30)
    for step_offset in range(-window, window + 1):
        try:
            expected = _compute_totp(secret, current_step + step_offset)
            if secrets.compare_digest(expected, code_clean):
                return True
        except Exception:
            pass
    return False

def generate_recovery_codes(count: int = 8) -> tuple[list[str], list[str]]:
    """
    Generate recovery codes.
    Returns (plaintext_codes_for_user, hashed_codes_for_db).
    """
    plaintext = []
    hashed = []
    for _ in range(count):
        raw = f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
        plaintext.append(raw)
        hashed.append(hash_secret_hmac(raw))
    return plaintext, hashed

def verify_and_consume_recovery_code(entered_code: str, hashed_codes: list[str]) -> tuple[bool, list[str]]:
    """
    Verify single-use recovery code. If matched, consume it and return updated list.
    """
    if not entered_code or not hashed_codes:
        return False, hashed_codes
    code_clean = entered_code.strip().upper().replace(" ", "")
    entered_hash = hash_secret_hmac(code_clean)
    for idx, stored_hash in enumerate(hashed_codes):
        if secrets.compare_digest(entered_hash, stored_hash):
            updated = list(hashed_codes)
            updated.pop(idx)
            return True, updated
    return False, hashed_codes

def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_customer_access_token(customer: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=CUSTOMER_ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(customer.get("id") or customer.get("_id")),
        "email": customer["email"].strip().lower(),
        "name": customer.get("name", "Customer"),
        "role": "customer",
        "token_version": int(customer.get("token_version", 1)),
        "exp": expire
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

async def get_current_admin(
    authorization: Optional[str] = Header(None),
    admin_token: Optional[str] = Cookie(None)
) -> dict:
    from app.database import get_database
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate admin credentials. Please log in.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif admin_token:
        token = admin_token

    if not token:
        raise credentials_exception

    payload = decode_access_token(token)
    if not payload:
        raise credentials_exception

    # Reject intermediate or single-purpose tokens (e.g. 2FA challenge tokens)
    if payload.get("purpose"):
        raise credentials_exception

    # Strictly separate customer and admin privileges
    if payload.get("role") == "customer":
        raise credentials_exception

    username: str = payload.get("sub")
    if not username:
        raise credentials_exception

    db = get_database()
    admin = await db.admins.find_one({"$or": [{"username": username}, {"email": username}]})
    if not admin:
        raise credentials_exception

    # Check token version for immediate session revocation upon logout or password change
    token_version = payload.get("token_version", 1)
    current_token_version = admin.get("token_version", 1)
    if token_version != current_token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin session has been revoked. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "id": admin.get("id", 1),
        "username": admin["username"],
        "email": admin["email"],
        "name": admin["name"],
        "role": admin["role"],
        "token_version": current_token_version
    }

async def get_current_admin_optional(
    authorization: Optional[str] = Header(None),
    admin_token: Optional[str] = Cookie(None)
) -> Optional[dict]:
    try:
        return await get_current_admin(authorization, admin_token)
    except HTTPException:
        return None

async def get_current_customer(
    authorization: Optional[str] = Header(None),
    customer_token: Optional[str] = Cookie(None)
) -> dict:
    from app.database import get_database
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate customer credentials. Please log in.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = None
    if authorization:
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        else:
            token = authorization.strip()
    elif customer_token:
        token = customer_token

    if not token:
        raise credentials_exception

    payload = decode_access_token(token)
    if not payload:
        raise credentials_exception

    if payload.get("role") != "customer":
        raise credentials_exception

    email: str = payload.get("email")
    if not email:
        raise credentials_exception

    db = get_database()
    customer = await db.customers.find_one({"email": email.strip().lower()})
    if not customer:
        raise credentials_exception

    # Check token version for immediate session revocation upon password reset or logout
    token_version = payload.get("token_version", 1)
    current_token_version = customer.get("token_version", 1)
    if token_version != current_token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "id": customer.get("id") or str(customer.get("_id")),
        "name": customer.get("name", "Customer"),
        "email": customer["email"],
        "phone": customer.get("phone", ""),
        "address": customer.get("address", ""),
        "token_version": current_token_version,
        "created_at": customer.get("created_at")
    }

async def get_current_customer_optional(
    authorization: Optional[str] = Header(None),
    customer_token: Optional[str] = Cookie(None)
) -> Optional[dict]:
    try:
        return await get_current_customer(authorization, customer_token)
    except Exception:
        return None
