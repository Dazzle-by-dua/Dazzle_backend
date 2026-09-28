import os
import shutil
import datetime
from typing import List
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from app.config import UPLOAD_DIR
from app.database import get_database, clean_doc, clean_docs
from app.models.schemas import MediaOut
from app.security import get_current_admin

router = APIRouter(prefix="/api/media", tags=["Media Assets"])

@router.get("", response_model=List[MediaOut])
async def get_media_list():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    db = get_database()

    db_rows = {r["filename"]: r for r in await db.media.find({}).to_list(length=500)}
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    results = []

    for item in UPLOAD_DIR.iterdir():
        if item.is_file() and not item.name.startswith("."):
            fname = item.name
            fsize = item.stat().st_size
            if fname in db_rows:
                record = clean_doc(db_rows[fname])
                results.append(record)
            else:
                title = fname.rsplit(".", 1)[0].replace("_", " ").title()
                url = f"/uploads/{fname}"
                last_m = await db.media.find({}).sort("id", -1).limit(1).to_list(1)
                mid = (last_m[0]["id"] + 1) if last_m else 1

                doc = {
                    "id": mid,
                    "filename": fname,
                    "title": title,
                    "type": "Product Asset",
                    "url": url,
                    "size": fsize,
                    "mime_type": "image/jpeg",
                    "created_at": now_iso
                }
                await db.media.insert_one(doc)
                results.append(clean_doc(doc))

    return results

@router.post("/upload", response_model=MediaOut)
async def upload_media(
    file: UploadFile = File(...),
    title: str = Form(None),
    asset_type: str = Form("Product Asset"),
    admin: dict = Depends(get_current_admin)
):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    db = get_database()

    original_name = Path(file.filename).name
    clean_name = original_name.replace(" ", "_").lower()
    target_path = UPLOAD_DIR / clean_name

    with target_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    fsize = target_path.stat().st_size
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    disp_title = title or original_name.rsplit(".", 1)[0].replace("_", " ").title()
    url = f"/uploads/{clean_name}"

    existing = await db.media.find_one({"filename": clean_name})
    if existing:
        await db.media.update_one(
            {"filename": clean_name},
            {"$set": {
                "title": disp_title,
                "type": asset_type,
                "url": url,
                "size": fsize,
                "mime_type": file.content_type or "image/jpeg",
                "created_at": now_iso
            }}
        )
        mid = existing["id"]
    else:
        last_m = await db.media.find({}).sort("id", -1).limit(1).to_list(1)
        mid = (last_m[0]["id"] + 1) if last_m else 1
        await db.media.insert_one({
            "id": mid,
            "filename": clean_name,
            "title": disp_title,
            "type": asset_type,
            "url": url,
            "size": fsize,
            "mime_type": file.content_type or "image/jpeg",
            "created_at": now_iso
        })

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
async def delete_media(filename: str, admin: dict = Depends(get_current_admin)):
    clean_name = Path(filename).name
    target_path = UPLOAD_DIR / clean_name

    if target_path.exists():
        try:
            target_path.unlink()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete file from disk: {e}")

    db = get_database()
    await db.media.delete_one({"filename": clean_name})
    return {"success": True, "message": f"Media '{clean_name}' deleted."}
