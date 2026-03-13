from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from backend.services.job_sources import fetch_simplify_jobs, normalize_job_types
from backend.services.db_tracker import get_jobs, get_job_by_id
from backend.services.scout_processor import ScoutProcessor
from backend.utils.url_matcher import find_job_by_url

router = APIRouter(prefix="/api/scout", tags=["scout"])
processor = ScoutProcessor()


@router.post("/run")
def run_scout(background_tasks: BackgroundTasks):
    """
    Manual trigger to start the Scout pipeline. 
    Fetches jobs from GitHub, filters for duplicates, and queues them 
    for background scraping/scoring.

    Args:
        background_tasks (BackgroundTasks): FastAPI background tasks.

    Returns:
        dict: Summary of jobs found and queued.
    """
    input_job_types = processor.settings.get("job_types", ["internship"])
    recognized_job_types, ignored_job_types = normalize_job_types(
        input_job_types)

    if not recognized_job_types:
        return {
            "found": 0,
            "new": 0,
            "duplicates": 0,
            "input_job_types": input_job_types,
            "recognized_job_types": recognized_job_types,
            "ignored_job_types": ignored_job_types,
            "message": "No supported job_types configured. Use internship, newgrad, or fulltime."
        }

    # Fetch initial batch
    raw_jobs = fetch_simplify_jobs(recognized_job_types)

    new_jobs = []
    for job in raw_jobs:
        if not get_job_by_id(job.get("job_id")):
            job.update({"status": "found", "score": 0, "reason": ""})
            from backend.services.db_tracker import add_job
            add_job(job)
            new_jobs.append(job)

    if new_jobs:
        background_tasks.add_task(processor.process_jobs_bg, new_jobs)

    duplicates = len(raw_jobs) - len(new_jobs)

    return {
        "found": len(raw_jobs),
        "new": len(new_jobs),
        "duplicates": duplicates,
        "input_job_types": input_job_types,
        "recognized_job_types": recognized_job_types,
        "ignored_job_types": ignored_job_types,
        "message": f"Triggered knockout pipeline for {len(new_jobs)} jobs ({duplicates} duplicates skipped)."
    }


@router.get("/jobs")
def get_scout_jobs(status: str = None):
    """
    Retrieves all tracked jobs from the database, optionally filtered by status.
    """
    return get_jobs(status=status)


@router.get("/jobs/{job_id}")
def get_job_details_api(job_id: str):
    """
    Fetches comprehensive details for a specific job, merging DB records 
    with local filesystem-first JD JSONs.
    """
    job_data = get_job_by_id(job_id)
    if not job_data:
        return {}

    from backend.services.db_tracker import load_job_details
    local_details = load_job_details(job_id)
    if local_details:
        job_data["description"] = local_details.get("description", "")

    return job_data


class OrganicTrackRequest(BaseModel):
    url: str
    title: Optional[str] = ""
    company: Optional[str] = ""
    page_text: Optional[str] = ""


@router.get("/check_url")
def check_url_tracked(url: str):
    """
    Check if a URL is already tracked. 
    Uses normalized matching to identify the same job across different parameters.
    """
    jobs = get_jobs()
    matched = find_job_by_url(jobs, url)
    if matched:
        return {"tracked": True, "job": matched}
    return {"tracked": False}


@router.post("/organic")
def organic_track_and_score(payload: OrganicTrackRequest):
    """
    Organic tracking endpoint used by the extension when an unknown job is encountered.
    Extracts, scores, and saves job data automatically.
    """
    res = processor.track_organic_job(
        url=payload.url,
        title=payload.title,
        company=payload.company,
        page_text=payload.page_text
    )
    return res
