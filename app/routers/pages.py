import json
from fastapi import APIRouter, Depends
from app.database import get_db
from app.models.schemas import PagesContent
from app.security import get_current_admin
from app.seed_data import DEFAULT_PAGES

router = APIRouter(prefix="/api/pages", tags=["Static Pages & Content"])

@router.get("", response_model=PagesContent)
def get_pages_content():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM pages WHERE key = 'main';")
        row = cursor.fetchone()
        if not row:
            return DEFAULT_PAGES
        return json.loads(row["data"])

@router.put("", response_model=PagesContent)
def update_pages_content(payload: PagesContent, admin: dict = Depends(get_current_admin)):
    data_dict = payload.model_dump()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO pages (key, data) VALUES ('main', ?)
               ON CONFLICT(key) DO UPDATE SET data = excluded.data;""",
            (json.dumps(data_dict),)
        )
    return data_dict
