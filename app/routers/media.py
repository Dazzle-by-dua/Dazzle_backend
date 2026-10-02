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
from app.cloudinary_service import (
    is_cloudinary_configured,
    upload_image_to_cloudinary,
    delete_image_from_cloudinary
)

router = APIRouter(prefix="/api/media", tags=["Media Assets"])

@router.get("", response_model=List[MediaOut])
async def get_media_list():
    """Retrieve all media assets from MongoDB and local uploads."""
    db = get_database()
    media_records = await db.media.find({}).sort("id", -1).to_list(length=500)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    results = [clean_doc(m) for m in media_records]

    # Also sync any existing local files into database if not yet tracked
    if UPLOAD_DIR.exists():
        existing_filenames = {m.get("filename") for m in results if m.get("filename")}
        for item in UPLOAD_DIR.iterdir():
            if item.is_file() and not item.name.startswith("."):
                fname = item.name
                if fname not in existing_filenames:
                    fsize = item.stat().st_size
                    title = fname.rsplit(".", 1)[0].replace("_", " ").title()
                    url = f"/uploads/{fname}"
                    mid = len(results) + 1
                    doc = {
                        "id": mid,
                        "filename": fname,
                        "title": title,
                        "type": "Local Asset",
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
    """
    Upload media to Cloudinary (if configured) or local storage as fallback.
    Persists asset document to MongoDB.
    """
    db = get_database()
    original_name = Path(file.filename or "media.jpg").name
    disp_title = title or original_name.rsplit(".", 1)[0].replace("_", " ").title()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if is_cloudinary_configured():
        cloud_res = await upload_image_to_cloudinary(
            file_content=file_bytes,
            filename=original_name,
            folder="dazzle_by_dua"
        )
        url = cloud_res["secure_url"]
        public_id = cloud_res["public_id"]
        fsize = cloud_res.get("bytes", len(file_bytes))
        asset_kind = "Cloudinary Asset"
    else:
        # Fallback to local disk
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        clean_name = original_name.replace(" ", "_").lower()
        target_path = UPLOAD_DIR / clean_name
        with target_path.open("wb") as buffer:
            buffer.write(file_bytes)
        fsize = target_path.stat().st_size
        url = f"/uploads/{clean_name}"
        public_id = None
        asset_kind = asset_type

    last_m = await db.media.find({}).sort("id", -1).limit(1).to_list(1)
    mid = (last_m[0]["id"] + 1) if last_m and "id" in last_m[0] else 1

    doc = {
        "id": mid,
        "filename": original_name,
        "title": disp_title,
        "type": asset_kind,
        "url": url,
        "secure_url": url,
        "public_id": public_id,
        "size": fsize,
        "mime_type": file.content_type or "image/jpeg",
        "created_at": now_iso
    }
    await db.media.insert_one(doc)

    return {
        "id": mid,
        "filename": original_name,
        "title": disp_title,
        "type": asset_kind,
        "url": url,
        "size": fsize,
        "mime_type": file.content_type or "image/jpeg",
        "created_at": now_iso
    }

@router.delete("/{identifier}")
async def delete_media(identifier: str, admin: dict = Depends(get_current_admin)):
    """Delete media asset from Cloudinary / disk and MongoDB."""
    db = get_database()
    
    # Try finding by public_id, filename, or string id
    query = {"$or": [
        {"filename": identifier},
        {"public_id": identifier}
    ]}
    if identifier.isdigit():
        query["$or"].append({"id": int(identifier)})

    record = await db.media.find_one(query)
    
    if record:
        if record.get("public_id") and is_cloudinary_configured():
            try:
                await delete_image_from_cloudinary(record["public_id"])
            except Exception as e:
                pass

        if record.get("filename"):
            clean_name = Path(record["filename"]).name
            target_path = UPLOAD_DIR / clean_name
            if target_path.exists():
                try:
                    target_path.unlink()
                except Exception:
                    pass

        await db.media.delete_one({"_id": record["_id"]})
        return {"success": True, "message": f"Media '{identifier}' deleted."}

    # If file exists on disk anyway
    clean_name = Path(identifier).name
    target_path = UPLOAD_DIR / clean_name
    if target_path.exists():
        try:
            target_path.unlink()
        except Exception:
            pass

    await db.media.delete_one({"filename": clean_name})
    return {"success": True, "message": f"Media '{identifier}' deleted."}
