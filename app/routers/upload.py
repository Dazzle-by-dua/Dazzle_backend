import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Query
from pydantic import BaseModel
from app.database import get_database, clean_doc
from app.security import get_current_admin
from app.cloudinary_service import (
    is_cloudinary_configured,
    upload_image_to_cloudinary,
    delete_image_from_cloudinary,
    get_cloudinary_health
)

router = APIRouter(prefix="/api/upload", tags=["Cloudinary Upload"])

class DeleteImageRequest(BaseModel):
    public_id: str

@router.get("/status")
async def get_upload_status():
    """Check if Cloudinary image upload system is configured and verified."""
    health = get_cloudinary_health()
    return {
        "status": health["status"],
        "cloudinary_configured": health["configured"],
        "cloudinary_verified": health["verified"],
        "cloud_name": health["cloud_name"],
        "storage": "cloudinary" if health["verified"] else ("unverified" if health["configured"] else "not_configured")
    }

@router.post("/image")
async def upload_image(
    file: UploadFile = File(...),
    folder: str = Form("dazzle_by_dua"),
    title: Optional[str] = Form(None),
    admin: dict = Depends(get_current_admin)
):
    """
    Upload an image from device directly to Cloudinary.
    Saves image metadata to MongoDB media collection and returns secure URL.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Only image files (JPEG, PNG, WEBP, GIF, SVG, AVIF) are allowed."
        )

    # Read file buffer
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    original_filename = Path(file.filename or "image.jpg").name
    display_title = title or original_filename.rsplit(".", 1)[0].replace("_", " ").title()

    # Upload to Cloudinary
    cloud_result = await upload_image_to_cloudinary(
        file_content=file_bytes,
        filename=original_filename,
        folder=folder
    )

    secure_url = cloud_result["secure_url"]
    public_id = cloud_result["public_id"]

    # Save reference to MongoDB 'media' collection
    db = get_database()
    last_m = await db.media.find({}).sort("id", -1).limit(1).to_list(1)
    mid = (last_m[0]["id"] + 1) if last_m and "id" in last_m[0] else 1

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    media_doc = {
        "id": mid,
        "filename": original_filename,
        "title": display_title,
        "type": "Cloudinary Asset",
        "url": secure_url,
        "secure_url": secure_url,
        "public_id": public_id,
        "size": cloud_result.get("bytes", len(file_bytes)),
        "mime_type": file.content_type,
        "created_at": now_iso
    }
    await db.media.insert_one(media_doc)

    return {
        "success": True,
        "secure_url": secure_url,
        "url": secure_url,
        "public_id": public_id,
        "filename": original_filename,
        "format": cloud_result.get("format"),
        "size": cloud_result.get("bytes"),
        "width": cloud_result.get("width"),
        "height": cloud_result.get("height"),
        "created_at": now_iso
    }

@router.delete("/image")
async def delete_image(
    payload: DeleteImageRequest,
    admin: dict = Depends(get_current_admin)
):
    """
    Delete an image from Cloudinary by public_id and remove from MongoDB.
    """
    public_id = payload.public_id
    if not public_id:
        raise HTTPException(status_code=400, detail="public_id is required.")

    # Delete from Cloudinary
    cloud_res = await delete_image_from_cloudinary(public_id)

    # Remove from MongoDB media collection if present
    db = get_database()
    await db.media.delete_many({"public_id": public_id})

    return {
        "success": True,
        "message": f"Image with public_id '{public_id}' deleted from Cloudinary.",
        "result": cloud_res
    }
