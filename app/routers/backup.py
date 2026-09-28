from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from app.database import export_all_data, import_all_data, reset_all_data
from app.security import get_current_admin

router = APIRouter(prefix="/api/backup", tags=["Database Backup & Restore"])

@router.get("/export")
async def export_store_backup(admin: dict = Depends(get_current_admin)) -> Dict[str, Any]:
    """Exports complete store data in format 100% identical to DazzleStore.exportAll()"""
    return await export_all_data()

@router.post("/import")
async def import_store_backup(payload: Dict[str, Any], admin: dict = Depends(get_current_admin)):
    """Imports complete store data in format 100% identical to DazzleStore.importAll()"""
    success = await import_all_data(payload)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to import store data. Please check JSON structure.")
    return {"success": True, "message": "Store data successfully restored from backup!"}

@router.post("/reset")
async def reset_store_to_defaults(admin: dict = Depends(get_current_admin)):
    """Resets store data to default demo state, matching DazzleStore.resetAll()"""
    await reset_all_data()
    return {"success": True, "message": "Store successfully reset to initial factory demo state."}
