from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from backend.services.db_tracker import (
    get_jobs, get_job_by_id, 
    update_job, get_stats, get_db_connection
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

@router.delete("/{job_id}")
def delete_job(job_id: str):
    """Permanently deletes a job record from the database."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Job not found")
    return {"deleted": True, "job_id": job_id}

@router.get("/export")
def export_excel():
    if not EXCEL_PATH.exists():
        raise HTTPException(status_code=404, detail="Excel file not found")
        
    return FileResponse(
        path=EXCEL_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="tracked_jobs.xlsx"
    )
