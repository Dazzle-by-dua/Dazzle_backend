import os
from pathlib import Path
from dotenv import load_dotenv

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))

# Automatically load variables from .env
load_dotenv(BASE_DIR / ".env")

# MongoDB Settings
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DB = (os.getenv("MONGODB_DB") or "dazzle_by_dua").strip()

# Environment Mode
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = (
    ENVIRONMENT in ("production", "prod")
    or os.getenv("RENDER") == "true"
    or os.getenv("NODE_ENV") == "production"
)

# Known insecure default keys that must never be used in production
INSECURE_SECRET_KEYS = {
    "dazzle_fine_jewellery_dua_jwt_secret_key_2025_prod_secure",
    "your_secure_jwt_secret_key_here",
    "secret",
    "secret123",
    "changeme",
    "admin",
    "admin123"
}

# Security & JWT
raw_secret = os.getenv("SECRET_KEY", "").strip()
if IS_PRODUCTION:
    if not raw_secret or raw_secret in INSECURE_SECRET_KEYS or len(raw_secret) < 32:
        raise RuntimeError(
            "CRITICAL SECURITY CONFIGURATION ERROR: SECRET_KEY is missing, insecure, or using a known default in production. "
            "Set a cryptographically strong SECRET_KEY (minimum 32 characters) in your environment variables."
        )
    SECRET_KEY = raw_secret
else:
    import secrets
    import logging
    if raw_secret and raw_secret not in INSECURE_SECRET_KEYS:
        SECRET_KEY = raw_secret
    else:
        logging.getLogger("dazzle.config").warning(
            "WARNING: SECRET_KEY is not set or uses an insecure default in development. "
            "Generated an ephemeral development key. Set SECRET_KEY in your .env for persistent sessions."
        )
        SECRET_KEY = secrets.token_urlsafe(32)

ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours

# Server Host & Port (0.0.0.0 binds to all network interfaces on Render)
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# CORS
cors_raw = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS = [orig.strip() for orig in cors_raw.split(",") if orig.strip()]

# Cloudinary Image Storage
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "").strip()
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "").strip()
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "").strip()

# Razorpay Payment Gateway
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()


