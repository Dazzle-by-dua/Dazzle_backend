import datetime
from fastapi import APIRouter, HTTPException, status, Depends, Response
from app.database import get_db
from app.security import verify_password, create_access_token, get_current_admin
from app.models.schemas import AdminLoginRequest, AdminLoginResponse, AdminProfile

router = APIRouter(prefix="/api/auth", tags=["Admin Authentication"])

@router.post("/login", response_model=AdminLoginResponse)
def login(payload: AdminLoginRequest, response: Response):
    clean_id = payload.username.strip().lower()
    clean_pass = payload.password.strip()

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, password_hash, name, role FROM admins WHERE LOWER(username) = ? OR LOWER(email) = ?", (clean_id, clean_id))
        admin = cursor.fetchone()

        if not admin or not verify_password(clean_pass, admin["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid admin credentials. Please check your username/email and password."
            )

        token_expires = datetime.timedelta(days=7 if payload.rememberMe else 1)
        token = create_access_token(
            data={"sub": admin["username"], "email": admin["email"], "role": admin["role"]},
            expires_delta=token_expires
        )

        response.set_cookie(
            key="admin_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=int(token_expires.total_seconds())
        )

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

@router.get("/me", response_model=AdminProfile)
def get_current_admin_profile(current_admin: dict = Depends(get_current_admin)):
    return {
        "user": current_admin["name"],
        "email": current_admin["email"],
        "role": current_admin["role"]
    }

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="admin_token")
    return {"success": True, "message": "Logged out successfully."}
