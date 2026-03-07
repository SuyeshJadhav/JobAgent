from fastapi import APIRouter, HTTPException
from backend.services.db_tracker import get_job_by_id

router = APIRouter()

@router.get("/{job_id}/payload")
def get_apply_payload(job_id: str):
    """
    Returns the application payload for the browser extension.
    """
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        "job_id": job.get("job_id"),
        "company": job.get("company"),
        "resume_path": job.get("resume_path"),
        "cover_letter_path": job.get("cover_letter_path")
    }
