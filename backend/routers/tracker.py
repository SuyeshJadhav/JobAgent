from fastapi import APIRouter
from backend.services.local_tracker import get_jobs, update_status
from pydantic import BaseModel

router = APIRouter(prefix="/api/tracker", tags=["tracker"])

class StatusUpdate(BaseModel):
    status: str
    notes: str = ""

@router.get("/stats")
def get_tracker_stats():
    jobs = get_jobs(status=None)
    stats = {}
    for job in jobs:
        st = job.get("status", "unknown")
        stats[st] = stats.get(st, 0) + 1
    return stats

@router.patch("/{job_id}/status")
def patch_job_status(job_id: str, payload: StatusUpdate):
    update_status(job_id, payload.status, notes=payload.notes)
    return {"status": "success", "job_id": job_id, "new_status": payload.status}
