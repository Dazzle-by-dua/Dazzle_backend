import hmac
import hashlib
import datetime
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

    username: str = payload.get("sub")
    if not username:
        raise credentials_exception

    db = get_database()
    admin = await db.admins.find_one({"$or": [{"username": username}, {"email": username}]})
    if not admin:
        raise credentials_exception

    return {
        "id": admin.get("id", 1),
        "username": admin["username"],
        "email": admin["email"],
        "name": admin["name"],
        "role": admin["role"]
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
    except HTTPException:
        return None
