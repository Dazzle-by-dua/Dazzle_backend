from typing import Dict, Any
from fastapi import APIRouter, Depends
from app.database import get_database
from app.security import get_current_admin

router = APIRouter(prefix="/api/homepage", tags=["Homepage Configuration"])

@router.get("")
async def get_homepage_config() -> Dict[str, Any]:
    db = get_database()
    items = await db.homepage.find({}).to_list(length=100)
    return {doc["section_key"]: doc["data"] for doc in items if "section_key" in doc and "data" in doc}

@router.put("")
async def update_homepage_config(payload: Dict[str, Any], admin: dict = Depends(get_current_admin)):
    db = get_database()
    for sec_key, sec_data in payload.items():
        await db.homepage.update_one(
            {"section_key": sec_key},
            {"$set": {"section_key": sec_key, "data": sec_data}},
            upsert=True
        )
    return await get_homepage_config()

@router.patch("/{section_key}")
async def update_homepage_section(section_key: str, payload: Dict[str, Any], admin: dict = Depends(get_current_admin)):
    db = get_database()
    existing = await db.homepage.find_one({"section_key": section_key})
    current_data = existing["data"] if existing and "data" in existing else {}
    current_data.update(payload)

    await db.homepage.update_one(
        {"section_key": section_key},
        {"$set": {"section_key": section_key, "data": current_data}},
        upsert=True
    )
    return {section_key: current_data}
