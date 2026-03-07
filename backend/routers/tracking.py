from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
from typing import Optional
from backend.services.sheets_manager import GoogleSheetsManager
from backend.services.job_sources import fetch_simplify_jobs
from backend.services.excel_formatter import format_excel, sync_db_to_excel

router = APIRouter(tags=["Tracking"])
sheets_manager = GoogleSheetsManager()

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
        date_added = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheets_manager.append_job_row(
            title=payload.title,
            company=payload.company,
            url=payload.url,
            status="Saved",
            date_added=date_added
        )
        return {"status": "success", "message": "Job tracked successfully"}
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
            raise HTTPException(status_code=400, detail="No valid job types provided.")

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

        # 3. Batch-add to Sheets (handles dedup internally)
        result = sheets_manager.batch_append_job_rows(sheet_rows)

        # 5. Auto-format the Excel file
        try:
            format_excel()
        except Exception as fmt_err:
            print(f"[WARN] Excel formatting failed: {fmt_err}")

        return {
            "status": "success",
            "message": f"Synced {result['added']} new jobs to Sheets ({result['skipped']} duplicates skipped).",
            "total_fetched": len(jobs),
            "added": result["added"],
            "skipped": result["skipped"]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/format_excel")
def format_excel_endpoint():
    """
    Manual trigger to sync the tracked_jobs.db into the Excel spreadsheet 
    and apply professional formatting (alternating row colors, auto-fit).
    
    Returns:
        dict: Success message.
    """
    try:
        sync_db_to_excel()
        return {"status": "success", "message": "Synced tracked_jobs.db to Excel."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
