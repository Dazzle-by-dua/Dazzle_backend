from fastapi import APIRouter, Depends
from app.database import get_database
from app.models.schemas import PagesContent
from app.security import get_current_admin
from app.seed_data import DEFAULT_PAGES

router = APIRouter(prefix="/api/pages", tags=["Static Pages & Content"])

@router.get("", response_model=PagesContent)
async def get_pages_content():
    db = get_database()
    row = await db.pages.find_one({"key": "main"})
    if not row or "data" not in row:
        return DEFAULT_PAGES
    return row["data"]

@router.put("", response_model=PagesContent)
async def update_pages_content(payload: PagesContent, admin: dict = Depends(get_current_admin)):
    data_dict = payload.model_dump()
    db = get_database()
    await db.pages.update_one(
        {"key": "main"},
        {"$set": {"key": "main", "data": data_dict}},
        upsert=True
    )
    return data_dict
