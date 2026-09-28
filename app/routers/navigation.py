import json
from fastapi import APIRouter, HTTPException, Depends
from app.database import get_db
from app.models.schemas import NavigationConfig, NavItem
from app.security import get_current_admin
from app.seed_data import DEFAULT_NAVIGATION

router = APIRouter(prefix="/api/navigation", tags=["Navigation Menus"])

@router.get("", response_model=NavigationConfig)
def get_navigation():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM navigation WHERE key = 'main';")
        row = cursor.fetchone()
        if not row:
            return DEFAULT_NAVIGATION
        return json.loads(row["data"])

@router.put("", response_model=NavigationConfig)
def update_navigation(payload: NavigationConfig, admin: dict = Depends(get_current_admin)):
    data_dict = payload.model_dump()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO navigation (key, data) VALUES ('main', ?)
               ON CONFLICT(key) DO UPDATE SET data = excluded.data;""",
            (json.dumps(data_dict),)
        )
    return data_dict

@router.post("/{section}")
def add_nav_item(section: str, item: NavItem, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM navigation WHERE key = 'main';")
        row = cursor.fetchone()
        nav_data = json.loads(row["data"]) if row else DEFAULT_NAVIGATION

        if section not in nav_data:
            nav_data[section] = []

        nav_data[section].append(item.model_dump())

        cursor.execute(
            """INSERT INTO navigation (key, data) VALUES ('main', ?)
               ON CONFLICT(key) DO UPDATE SET data = excluded.data;""",
            (json.dumps(nav_data),)
        )

    return nav_data

@router.delete("/{section}/{index}")
def delete_nav_item(section: str, index: int, admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM navigation WHERE key = 'main';")
        row = cursor.fetchone()
        nav_data = json.loads(row["data"]) if row else DEFAULT_NAVIGATION

        if section not in nav_data or index < 0 or index >= len(nav_data[section]):
            raise HTTPException(status_code=400, detail="Invalid section or index.")

        nav_data[section].pop(index)

        cursor.execute(
            """INSERT INTO navigation (key, data) VALUES ('main', ?)
               ON CONFLICT(key) DO UPDATE SET data = excluded.data;""",
            (json.dumps(nav_data),)
        )

    return nav_data
