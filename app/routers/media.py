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

import io
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_WIDTH = 5000
MAX_IMAGE_HEIGHT = 5000
MAX_IMAGE_PIXELS = 25_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP", "AVIF"}

def validate_image_signature(content: bytes) -> str:
    """
    Validate magic byte signatures and perform actual image decoding verification using Pillow.
    Rejects:
    - Empty, truncated, or corrupted streams
    - SVG, XML, and HTML script payloads (Stored XSS protection)
    - Decompression bombs and oversized image dimensions (>5000px or >25MP)
    - Spoofed files where extensions/headers do not match decodable raster image data
    Returns the detected format in lowercase ("jpeg", "png", "gif", "webp", "avif").
    """
    if len(content) < 12:
        raise HTTPException(
            status_code=400,
            detail="Invalid image file: content too short or corrupted."
        )

    # Safely reject SVG/XML/HTML uploads due to script injection (Stored XSS) and XXE risks
    lower_head = content[:512].lower()
    if b"<svg" in lower_head or b"<?xml" in lower_head or b"<!doctype svg" in lower_head or b"<html" in lower_head or b"<script" in lower_head:
        raise HTTPException(
            status_code=400,
            detail="SVG uploads are disabled for security reasons (script injection risk). Please use standard raster formats (JPEG, PNG, WEBP, GIF, AVIF)."
        )

    # Magic byte check
    is_magic_ok = False
    if content.startswith(b"\xff\xd8\xff"):
        is_magic_ok = True
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        is_magic_ok = True
    elif content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        is_magic_ok = True
    elif content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP":
        is_magic_ok = True
    elif len(content) >= 12 and content[4:8] == b"ftyp" and content[8:12] in (b"avif", b"avis", b"mif1"):
        is_magic_ok = True

    if not is_magic_ok:
        raise HTTPException(
            status_code=400,
            detail="Invalid image contents: file signature does not match any allowed image format (JPEG, PNG, WEBP, GIF, AVIF)."
        )

    # Full structural decoding and decompression bomb verification using Pillow
    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()
            fmt = (img.format or "").upper()
            if fmt not in ALLOWED_IMAGE_FORMATS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported image format '{fmt}'. Allowed formats: JPEG, PNG, WEBP, GIF, AVIF."
                )

        # Inspect dimensions after verify
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
            if width <= 0 or height <= 0:
                raise HTTPException(status_code=400, detail="Invalid image dimensions.")
            if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image dimensions exceed maximum allowed limit of {MAX_IMAGE_WIDTH}x{MAX_IMAGE_HEIGHT}px (uploaded: {width}x{height}px)."
                )
            if (width * height) > MAX_IMAGE_PIXELS:
                raise HTTPException(
                    status_code=400,
                    detail="Image pixel count exceeds maximum safe limit (decompression bomb protection)."
                )
            return fmt.lower()
    except Image.DecompressionBombError:
        raise HTTPException(
            status_code=400,
            detail="Image rejected: decompression bomb detected."
        )
    except (UnidentifiedImageError, SyntaxError, ValueError) as err:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image contents: unable to decode image ({err})."
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Failed to decode and verify image file integrity."
        )

@router.post("/upload", response_model=MediaOut)
async def upload_media(
    file: UploadFile = File(...),
    title: str = Form(None),
    asset_type: str = Form("Product Asset"),
    admin: dict = Depends(get_current_admin)
):
    """
    Upload media to Cloudinary (if configured) or local storage as fallback.
    Validates file MIME-type, enforces 10MB limit via chunked streaming,
    verifies magic bytes signature, and persists asset document to MongoDB.
    """
    db = get_database()
    original_name = Path(file.filename or "media.jpg").name
    disp_title = title or original_name.rsplit(".", 1)[0].replace("_", " ").title()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Only image files (JPEG, PNG, WEBP, GIF, AVIF) are allowed."
        )

    # Enforce 10 MB limit while reading chunks before buffering entire stream into memory
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
    CHUNK_SIZE = 64 * 1024            # 64 KB
    chunks = []
    total_size = 0

    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Image size exceeds the 10 MB limit (uploaded: >10 MB). Please choose a smaller file."
            )
        chunks.append(chunk)

    if total_size == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    file_bytes = b"".join(chunks)

    # Validate actual file signature (magic bytes) to defeat MIME-spoofing and reject SVGs
    detected_format = validate_image_signature(file_bytes)
    detected_mime = f"image/{detected_format}"

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
        # Fallback to local disk with cleanup on error
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        import re
        safe_base = re.sub(r'[^a-zA-Z0-9_.-]', '_', original_name.rsplit(".", 1)[0]).lower()
        clean_name = f"{safe_base}.{detected_format}"
        target_path = UPLOAD_DIR / clean_name
        try:
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
                "mime_type": detected_mime,
                "created_at": now_iso
            }
            await db.media.insert_one(doc)
        except Exception as upload_err:
            if target_path.exists():
                try:
                    target_path.unlink()
                except Exception:
                    pass
            raise upload_err

        return {
            "id": mid,
            "filename": original_name,
            "title": disp_title,
            "type": asset_kind,
            "url": url,
            "size": fsize,
            "mime_type": detected_mime,
            "created_at": now_iso
        }

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
        "mime_type": detected_mime,
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
        "mime_type": detected_mime,
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
