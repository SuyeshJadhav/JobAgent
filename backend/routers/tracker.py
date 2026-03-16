from fastapi import APIRouter, HTTPException
from backend.services.db_tracker import (
    get_jobs, update_job, get_stats, get_db_connection
)
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


@router.delete("/rejected")
def delete_rejected_jobs():
    """Permanently deletes all jobs with 'rejected' status."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM jobs WHERE status = 'rejected'")
        count = cursor.rowcount
        conn.commit()
    return {"deleted": True, "count": count}


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
