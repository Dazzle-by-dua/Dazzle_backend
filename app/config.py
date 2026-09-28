import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "dazzle.db")))

# Security & JWT
SECRET_KEY = os.getenv("SECRET_KEY", "dazzle_fine_jewellery_dua_jwt_secret_key_2025_prod_secure")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours

# Server Host & Port (0.0.0.0 allows binding across cloud hosts like Render)
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# CORS
cors_raw = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS = [orig.strip() for orig in cors_raw.split(",") if orig.strip()]
