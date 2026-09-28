import json
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from app.database import get_db
from app.security import get_current_admin

router = APIRouter(prefix="/api/homepage", tags=["Homepage Configuration"])

@router.get("")
def get_homepage_config() -> Dict[str, Any]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT section_key, data FROM homepage;")
        rows = cursor.fetchall()
        return {r["section_key"]: json.loads(r["data"]) for r in rows}

@router.put("")
def update_homepage_config(payload: Dict[str, Any], admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        for sec_key, sec_data in payload.items():
            cursor.execute(
                """INSERT INTO homepage (section_key, data) VALUES (?, ?)
                   ON CONFLICT(section_key) DO UPDATE SET data = excluded.data;""",
                (sec_key, json.dumps(sec_data))
            )
    return get_homepage_config()

@router.patch("/{section_key}")
def update_homepage_section(section_key: str, payload: Dict[str, Any], admin: dict = Depends(get_current_admin)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM homepage WHERE section_key = ?", (section_key,))
        row = cursor.fetchone()
        existing = json.loads(row["data"]) if row else {}
        existing.update(payload)

        cursor.execute(
            """INSERT INTO homepage (section_key, data) VALUES (?, ?)
               ON CONFLICT(section_key) DO UPDATE SET data = excluded.data;""",
            (section_key, json.dumps(existing))
        )
    return {section_key: existing}
