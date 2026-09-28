from fastapi import APIRouter, Depends
from app.database import get_database
from app.models.schemas import StoreSettings
from app.security import get_current_admin
from app.seed_data import DEFAULT_SETTINGS

router = APIRouter(prefix="/api/settings", tags=["Store Settings"])

@router.get("", response_model=StoreSettings)
async def get_store_settings():
    db = get_database()
    row = await db.settings.find_one({"key": "main"})
    if not row or "data" not in row:
        return DEFAULT_SETTINGS
    return row["data"]

@router.put("", response_model=StoreSettings)
async def update_store_settings(payload: StoreSettings, admin: dict = Depends(get_current_admin)):
    data_dict = payload.model_dump()
    db = get_database()
    await db.settings.update_one(
        {"key": "main"},
        {"$set": {"key": "main", "data": data_dict}},
        upsert=True
    )
    return data_dict
