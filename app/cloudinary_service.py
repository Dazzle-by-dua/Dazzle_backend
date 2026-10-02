import os
import logging
from typing import Optional, Dict, Any
import cloudinary
import cloudinary.uploader
import cloudinary.api
from fastapi import HTTPException
from app.config import (
    CLOUDINARY_CLOUD_NAME,
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET,
    CLOUDINARY_URL
)

logger = logging.getLogger("dazzle.cloudinary")

def is_cloudinary_configured() -> bool:
    """Check if Cloudinary environment credentials are set."""
    if CLOUDINARY_URL:
        return True
    return bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)

def init_cloudinary():
    """Initialize Cloudinary SDK with environment variables."""
    if CLOUDINARY_URL:
        cloudinary.config(cloudinary_url=CLOUDINARY_URL, secure=True)
        logger.info("Cloudinary initialized from CLOUDINARY_URL")
    elif is_cloudinary_configured():
        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET,
            secure=True
        )
        logger.info(f"Cloudinary initialized for cloud_name: {CLOUDINARY_CLOUD_NAME}")
    else:
        logger.warning("Cloudinary credentials are not configured.")

# Initialize on module load
init_cloudinary()

async def upload_image_to_cloudinary(
    file_content: Any,
    filename: Optional[str] = None,
    folder: str = "dazzle_by_dua"
) -> Dict[str, Any]:
    """
    Upload an image to Cloudinary and return secure URL and public_id.
    """
    if not is_cloudinary_configured():
        raise HTTPException(
            status_code=500,
            detail="Cloudinary is not configured. Please add CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET to your environment variables."
        )

    try:
        # Upload options
        upload_params = {
            "folder": folder,
            "resource_type": "image",
            "overwrite": True,
            "unique_filename": True
        }
        if filename:
            # Clean filename without extension for public_id suggestion
            clean_name = filename.rsplit(".", 1)[0].replace(" ", "_").lower()
            upload_params["public_id_prefix"] = clean_name

        result = cloudinary.uploader.upload(file_content, **upload_params)
        
        return {
            "secure_url": result.get("secure_url"),
            "public_id": result.get("public_id"),
            "format": result.get("format"),
            "bytes": result.get("bytes", 0),
            "width": result.get("width"),
            "height": result.get("height"),
            "created_at": result.get("created_at")
        }
    except Exception as e:
        logger.error(f"Cloudinary upload failed: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Cloudinary upload failed: {str(e)}"
        )

async def delete_image_from_cloudinary(public_id: str) -> Dict[str, Any]:
    """
    Delete an image from Cloudinary by its public_id.
    """
    if not is_cloudinary_configured():
        raise HTTPException(
            status_code=500,
            detail="Cloudinary is not configured."
        )

    try:
        result = cloudinary.uploader.destroy(public_id, invalidate=True)
        return result
    except Exception as e:
        logger.error(f"Cloudinary deletion failed for {public_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Cloudinary deletion failed: {str(e)}"
        )
