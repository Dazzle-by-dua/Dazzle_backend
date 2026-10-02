import os
import re
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

# Internal state tracking for Cloudinary health/verification
_cloudinary_state: Dict[str, Any] = {
    "configured": False,
    "verified": False,
    "cloud_name": None,
    "status": "uninitialized",
    "error": None
}

def _sanitize_cloudinary_error(msg: Any) -> str:
    """Mask any API secrets, passwords, or credentials from error messages."""
    text = str(msg)
    if CLOUDINARY_API_SECRET and CLOUDINARY_API_SECRET in text:
        text = text.replace(CLOUDINARY_API_SECRET, "[REDACTED]")
    # Mask any cloudinary:// API secret pattern: cloudinary://key:secret@cloud
    text = re.sub(r'cloudinary://([^:]+):([^@]+)@', r'cloudinary://\1:***@', text)
    return text

def is_cloudinary_configured() -> bool:
    """Check if Cloudinary environment credentials are set."""
    if CLOUDINARY_URL:
        return True
    return bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)

def init_cloudinary():
    """Configure the Cloudinary Python SDK with environment credentials."""
    global _cloudinary_state
    if CLOUDINARY_URL:
        cloudinary.config(cloudinary_url=CLOUDINARY_URL, secure=True)
        _cloudinary_state["configured"] = True
        _cloudinary_state["cloud_name"] = cloudinary.config().cloud_name
    elif is_cloudinary_configured():
        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET,
            secure=True
        )
        _cloudinary_state["configured"] = True
        _cloudinary_state["cloud_name"] = CLOUDINARY_CLOUD_NAME
    else:
        _cloudinary_state["configured"] = False
        _cloudinary_state["status"] = "not_configured"

# Initialize SDK configuration on module load
init_cloudinary()

def verify_cloudinary_connection() -> Dict[str, Any]:
    """
    Verify Cloudinary configuration and connectivity without uploading unnecessary files.
    Uses real authenticated ping API call. Logs clear verification message on success
    or safe error message on failure without leaking credentials.
    """
    global _cloudinary_state

    # Ensure configuration is fresh
    init_cloudinary()

    if not is_cloudinary_configured():
        _cloudinary_state["configured"] = False
        _cloudinary_state["verified"] = False
        _cloudinary_state["status"] = "not_configured"
        _cloudinary_state["error"] = "Cloudinary environment variables (CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET) not set."
        msg = "Cloudinary configuration: None (Credentials not set in environment)"
        print(msg)
        logger.warning(msg)
        return dict(_cloudinary_state)

    try:
        # Make a lightweight authenticated ping check to Cloudinary API (zero files uploaded)
        res = cloudinary.api.ping()
        if isinstance(res, dict) and res.get("status") == "ok":
            _cloudinary_state["configured"] = True
            _cloudinary_state["verified"] = True
            _cloudinary_state["status"] = "verified"
            _cloudinary_state["cloud_name"] = CLOUDINARY_CLOUD_NAME or cloudinary.config().cloud_name
            _cloudinary_state["error"] = None

            success_msg = "Cloudinary configuration detected and verified"
            print(success_msg)
            logger.info(success_msg)
            if _cloudinary_state["cloud_name"]:
                print(f"Cloudinary cloud name: {_cloudinary_state['cloud_name']}")
                logger.info(f"Cloudinary cloud name: {_cloudinary_state['cloud_name']}")
            return dict(_cloudinary_state)
        else:
            safe_err = f"Unexpected ping response: {res}"
            _cloudinary_state["verified"] = False
            _cloudinary_state["status"] = "failed"
            _cloudinary_state["error"] = safe_err
            fail_msg = f"Cloudinary verification failed: {safe_err}"
            print(fail_msg)
            logger.warning(fail_msg)
            return dict(_cloudinary_state)

    except Exception as e:
        safe_err = _sanitize_cloudinary_error(e)
        _cloudinary_state["verified"] = False
        _cloudinary_state["status"] = "failed"
        _cloudinary_state["error"] = safe_err
        fail_msg = f"Cloudinary verification failed: {safe_err}"
        print(fail_msg)
        logger.error(fail_msg)
        return dict(_cloudinary_state)

def get_cloudinary_health() -> Dict[str, Any]:
    """Return safe health check status of Cloudinary integration."""
    return {
        "status": "connected" if _cloudinary_state.get("verified") else (_cloudinary_state.get("status") or "unverified"),
        "configured": _cloudinary_state.get("configured", False),
        "verified": _cloudinary_state.get("verified", False),
        "cloud_name": _cloudinary_state.get("cloud_name"),
        "error": _cloudinary_state.get("error") if not _cloudinary_state.get("verified") else None
    }

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
        safe_err = _sanitize_cloudinary_error(e)
        logger.error(f"Cloudinary upload failed: {safe_err}")
        raise HTTPException(
            status_code=502,
            detail=f"Cloudinary upload failed: {safe_err}"
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
        safe_err = _sanitize_cloudinary_error(e)
        logger.error(f"Cloudinary deletion failed for {public_id}: {safe_err}")
        raise HTTPException(
            status_code=502,
            detail=f"Cloudinary deletion failed: {safe_err}"
        )
