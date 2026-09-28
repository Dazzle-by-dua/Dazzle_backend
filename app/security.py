import datetime
from typing import Optional
from fastapi import Depends, HTTPException, status, Header, Cookie
from jose import JWTError, jwt
import bcrypt
from app.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from app.database import get_db

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

def get_current_admin(
    authorization: Optional[str] = Header(None),
    admin_token: Optional[str] = Cookie(None)
) -> dict:
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

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, name, role, created_at FROM admins WHERE username = ? OR email = ?", (username, username))
        admin = cursor.fetchone()
        if not admin:
            raise credentials_exception

        return {
            "id": admin["id"],
            "username": admin["username"],
            "email": admin["email"],
            "name": admin["name"],
            "role": admin["role"]
        }

def get_current_admin_optional(
    authorization: Optional[str] = Header(None),
    admin_token: Optional[str] = Cookie(None)
) -> Optional[dict]:
    try:
        return get_current_admin(authorization, admin_token)
    except HTTPException:
        return None
