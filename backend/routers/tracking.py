import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from backend.services.job_sources import fetch_simplify_jobs


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Tracking"])


class TrackJobPayload(BaseModel):
    title: str
    company: str
    url: str


@router.post("/track_job")
def track_job(payload: TrackJobPayload):
    """
    Manually tracks a job by adding its metadata to Google Sheets/Excel.

    Args:
        payload (TrackJobPayload): Job title, company, and URL.

    Returns:
        dict: Success status and message.
    """
    try:
        logger.warning("Google Sheets sync not available")
        return {
            "status": "success",
            "message": "Google Sheets sync not available",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync_github_jobs")
def sync_github_jobs(
    job_types: str = Query(
        default="internship,newgrad",
        description="Comma-separated job types to sync: internship, newgrad"
    )
):
    """
    Fetches job listings from community GitHub repos (e.g., SimplifyJobs), 
    filters them, and batch-adds them to the tracking system.

    Args:
        job_types (str): Comma-separated list of types ('internship', 'newgrad').

    Returns:
        dict: Summary of additions and skipped duplicates.
    """
    try:
        types_list = [t.strip() for t in job_types.split(",") if t.strip()]
        if not types_list:
            raise HTTPException(
                status_code=400, detail="No valid job types provided.")

        # 1. Fetch filtered jobs from GitHub
        jobs = fetch_simplify_jobs(types_list)
        if not jobs:
            return {
                "status": "success",
                "message": "No matching jobs found from GitHub sources.",
                "added": 0,
                "skipped": 0,
                "total_fetched": 0
            }

        # 2. Prepare rows for batch insert
        date_added = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet_rows = []
        for job in jobs:
            sheet_rows.append({
                "title": job["title"],
                "company": job["company"],
                "url": job["apply_link"],
                "status": "GitHub Source",
                "date_added": date_added
            })

        # 3. Sheets sync is disabled after sheets_manager removal.
        logger.warning("Google Sheets sync not available")
        result = {"added": 0, "skipped": len(sheet_rows)}

        return {
            "status": "success",
            "message": "Google Sheets sync not available",
            "total_fetched": len(jobs),
            "added": result["added"],
            "skipped": result["skipped"]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
