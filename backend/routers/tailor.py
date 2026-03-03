import os
from pathlib import Path
from fastapi import APIRouter, HTTPException

from backend.services.resume_tailor import run_tailor
from backend.services.cover_letter import run_cover_letter
from backend.services.local_tracker import get_job_by_id, load_job_details, update_status
from backend.services.llm_client import get_settings

router = APIRouter(prefix="/api/tailor", tags=["tailor"])
OUTPUT_DIR = Path(__file__).parent.parent.parent / "outputs" / "applications"

@router.post("/{job_id}")
def run_tailor_endpoint(job_id: str):
    """Runs the full tailor pipeline for a job by fetching its details from Notion."""
    # 1. Get job from Notion
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found in tracking DB")
        
    # 2. Load full description
    details = load_job_details(job_id)
    if not details:
        raise HTTPException(status_code=404, detail="Job details file missing. Re-run scout.")
        
    # 3. Merge description
    job["description"] = details.get("description", "")
    
    # 4. Validate score
    settings = get_settings()
    threshold = int(settings.get("score_threshold", 6))
    if int(job.get("score", 0)) < threshold:
        raise HTTPException(status_code=400, detail="Job score below threshold")
        
    # 5. Validate status
    if job.get("status") != "shortlisted":
        raise HTTPException(status_code=400, detail="Job not in shortlisted status")
        
    # 6. Call run_tailor
    tailor_result = run_tailor(job)
    resume_path = tailor_result.get("pdf_path", "")

    # 7. Call run_cover_letter
    cover_result = run_cover_letter(job)
    cover_letter_path = cover_result.get("cover_letter_path", "")
    
    output_folder = tailor_result.get("output_dir", "") or cover_result.get("output_dir", "")
    
    # 8. Update Notion status
    update_kwargs = {}
    if resume_path:
        update_kwargs["ResumePath"] = resume_path
    if cover_letter_path:
        update_kwargs["CoverLetterPath"] = cover_letter_path
        
    update_status(job_id, "tailored", **update_kwargs)
    
    # 9. Return
    return {
        "job_id": job_id,
        "status": "tailored",
        "resume_path": str(resume_path),
        "cover_letter_path": str(cover_letter_path),
        "output_folder": str(output_folder)
    }

@router.get("/outputs")
def list_outputs():
    if not OUTPUT_DIR.exists():
        return {"folders": []}
        
    folders = []
    for d in OUTPUT_DIR.iterdir():
        if d.is_dir():
            folders.append(d.name)
    return {"folders": folders}
