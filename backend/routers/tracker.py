from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from backend.services.db_tracker import (
    get_jobs, get_job_by_id, 
    update_job, get_stats
)
from backend.services.excel_formatter import EXCEL_PATH
from pydantic import BaseModel

router = APIRouter(prefix="/api/tracker", tags=["tracker"])

class StatusUpdate(BaseModel):
    status: str
    notes: str = ""

@router.get("/stats")
def get_tracker_stats():
    return get_stats()

@router.get("/jobs")
def get_tracker_jobs(status: str = None):
    return get_jobs(status=status)

@router.patch("/{job_id}/status")
def patch_job_status(job_id: str, body: dict):
    # Using dict for body to allow arbitrary fields as requested in update_job(**body)
    success = update_job(job_id, **body)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"updated": True}

@router.get("/export")
def export_excel():
    if not EXCEL_PATH.exists():
        raise HTTPException(status_code=404, detail="Excel file not found")
        
    return FileResponse(
        path=EXCEL_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="tracked_jobs.xlsx"
    )
