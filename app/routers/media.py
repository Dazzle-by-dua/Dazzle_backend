import os
import shutil
import datetime
from typing import List
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from app.config import UPLOAD_DIR
from app.database import get_db
from app.models.schemas import MediaOut
from app.security import get_current_admin

router = APIRouter(prefix="/api/media", tags=["Media Assets"])

@router.get("", response_model=List[MediaOut])
def get_media_list():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM media ORDER BY id DESC;")
        db_rows = {r["filename"]: dict(r) for r in cursor.fetchall()}

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        results = []

        # Check all files in UPLOAD_DIR
        for item in UPLOAD_DIR.iterdir():
            if item.is_file() and not item.name.startswith("."):
                fname = item.name
                fsize = item.stat().st_size
                if fname in db_rows:
                    record = db_rows[fname]
                    results.append({
                        "id": record["id"],
                        "filename": record["filename"],
                        "title": record["title"],
                        "type": record["type"],
                        "url": record["url"],
                        "size": fsize,
                        "mime_type": record.get("mime_type", "image/jpeg"),
                        "created_at": record["created_at"]
                    })
                else:
                    # Register file in DB
                    title = fname.rsplit(".", 1)[0].replace("_", " ").title()
                    url = f"/uploads/{fname}"
                    cursor.execute(
                        """INSERT INTO media (filename, title, type, url, size, mime_type, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (fname, title, "Product Asset", url, fsize, "image/jpeg", now_iso)
                    )
                    new_id = cursor.lastrowid
                    results.append({
                        "id": new_id,
                        "filename": fname,
                        "title": title,
                        "type": "Product Asset",
                        "url": url,
                        "size": fsize,
                        "mime_type": "image/jpeg",
                        "created_at": now_iso
                    })

        return results

@router.post("/upload", response_model=MediaOut)
async def upload_media(
    file: UploadFile = File(...),
    title: str = Form(None),
    asset_type: str = Form("Product Asset"),
    admin: dict = Depends(get_current_admin)
):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    original_name = Path(file.filename).name
    clean_name = original_name.replace(" ", "_").lower()
    target_path = UPLOAD_DIR / clean_name

    with target_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    fsize = target_path.stat().st_size
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    disp_title = title or original_name.rsplit(".", 1)[0].replace("_", " ").title()
    url = f"/uploads/{clean_name}"

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM media WHERE filename = ?", (clean_name,))
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                """UPDATE media SET title = ?, type = ?, url = ?, size = ?, mime_type = ?, created_at = ? WHERE id = ?""",
                (disp_title, asset_type, url, fsize, file.content_type or "image/jpeg", now_iso, existing["id"])
            )
            mid = existing["id"]
        else:
            cursor.execute(
                """INSERT INTO media (filename, title, type, url, size, mime_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (clean_name, disp_title, asset_type, url, fsize, file.content_type or "image/jpeg", now_iso)
            )
            mid = cursor.lastrowid

    return {
        "id": mid,
        "filename": clean_name,
        "title": disp_title,
        "type": asset_type,
        "url": url,
        "size": fsize,
        "mime_type": file.content_type or "image/jpeg",
        "created_at": now_iso
    }

@router.delete("/{filename}")
def delete_media(filename: str, admin: dict = Depends(get_current_admin)):
    clean_name = Path(filename).name
    target_path = UPLOAD_DIR / clean_name

    if target_path.exists():
        try:
            target_path.unlink()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete file from disk: {e}")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM media WHERE filename = ?", (clean_name,))

    return {"success": True, "message": f"Media '{clean_name}' deleted."}
