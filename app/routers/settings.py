import json
from fastapi import APIRouter, Depends
from app.database import get_db
from app.models.schemas import StoreSettings
from app.security import get_current_admin
from app.seed_data import DEFAULT_SETTINGS

router = APIRouter(prefix="/api/settings", tags=["Store Settings"])

@router.get("", response_model=StoreSettings)
def get_store_settings():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM settings WHERE key = 'main';")
        row = cursor.fetchone()
        if not row:
            return DEFAULT_SETTINGS
        return json.loads(row["data"])

@router.put("", response_model=StoreSettings)
def update_store_settings(payload: StoreSettings, admin: dict = Depends(get_current_admin)):
    data_dict = payload.model_dump()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO settings (key, data) VALUES ('main', ?)
               ON CONFLICT(key) DO UPDATE SET data = excluded.data;""",
            (json.dumps(data_dict),)
        )
    return data_dict
