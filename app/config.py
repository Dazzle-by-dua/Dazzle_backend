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

# Security & JWT
SECRET_KEY = os.getenv("SECRET_KEY", "dazzle_fine_jewellery_dua_jwt_secret_key_2025_prod_secure")
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
