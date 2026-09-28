from fastapi import APIRouter, HTTPException, Depends
from app.database import get_database
from app.models.schemas import NavigationConfig, NavItem
from app.security import get_current_admin
from app.seed_data import DEFAULT_NAVIGATION

router = APIRouter(prefix="/api/navigation", tags=["Navigation Menus"])

@router.get("", response_model=NavigationConfig)
async def get_navigation():
    db = get_database()
    row = await db.navigation.find_one({"key": "main"})
    if not row or "data" not in row:
        return DEFAULT_NAVIGATION
    return row["data"]

@router.put("", response_model=NavigationConfig)
async def update_navigation(payload: NavigationConfig, admin: dict = Depends(get_current_admin)):
    data_dict = payload.model_dump()
    db = get_database()
    await db.navigation.update_one(
        {"key": "main"},
        {"$set": {"key": "main", "data": data_dict}},
        upsert=True
    )
    return data_dict

@router.post("/{section}")
async def add_nav_item(section: str, item: NavItem, admin: dict = Depends(get_current_admin)):
    db = get_database()
    row = await db.navigation.find_one({"key": "main"})
    nav_data = row["data"] if row and "data" in row else DEFAULT_NAVIGATION.copy()

    if section not in nav_data:
        nav_data[section] = []

    nav_data[section].append(item.model_dump())
    await db.navigation.update_one({"key": "main"}, {"$set": {"key": "main", "data": nav_data}}, upsert=True)
    return nav_data

@router.delete("/{section}/{index}")
async def delete_nav_item(section: str, index: int, admin: dict = Depends(get_current_admin)):
    db = get_database()
    row = await db.navigation.find_one({"key": "main"})
    nav_data = row["data"] if row and "data" in row else DEFAULT_NAVIGATION.copy()

    if section not in nav_data or index < 0 or index >= len(nav_data[section]):
        raise HTTPException(status_code=400, detail="Invalid section or index.")

    nav_data[section].pop(index)
    await db.navigation.update_one({"key": "main"}, {"$set": {"key": "main", "data": nav_data}}, upsert=True)
    return nav_data
