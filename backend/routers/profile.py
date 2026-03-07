import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.profile_rag import batch_fill_fields
from backend.services.resume_manager import evaluate_and_fetch_resume
from backend.services.db_tracker import add_job

router = APIRouter(prefix="/api/profile", tags=["profile"])
PROFILE_DIR = Path(__file__).parent.parent.parent / "profile"

class ProfileUpdate(BaseModel):
    content: str

class FillRequest(BaseModel):
    fields: list[str]
    job_url: str = ""
    company: str = ""
    job_description: str = ""

@router.get("")
def get_all_profiles():
    if not PROFILE_DIR.exists():
        return {}
    
    results = {}
    for f in PROFILE_DIR.glob("*.md"):
        results[f.name] = f.read_text(encoding="utf-8")
    return results

@router.post("/fill")
async def fill_application_fields(req: FillRequest):
    """Bridge for the browser extension to autofill forms via Profile RAG.
    Uses a single batched LLM call for all fields."""
    result = await asyncio.to_thread(
        batch_fill_fields,
        fields=req.fields,
        job_url=req.job_url,
        company=req.company,
    )

    # If job description is present, also fetch the resume (scored/tailored)
    if req.job_description:
        print(f"JD found. Triggering resume evaluation...")
        resume_data = evaluate_and_fetch_resume(req.job_description)
        result["resume_automation"] = resume_data

    return result

class CompleteRequest(BaseModel):
    job_url: str
    company: str
    is_generated: bool = False
    generated_resume_path: str = ""

@router.post("/application_complete")
def application_complete(req: CompleteRequest):
    """Cleanup tailored files and track job in CSV."""
    import os
    from datetime import datetime
    from backend.services.db_tracker import get_jobs, update_job
    from backend.utils.url_matcher import find_job_by_url
    from backend.services.excel_formatter import sync_db_to_excel
    
    jobs = get_jobs()
    matched_job = find_job_by_url(jobs, req.job_url)

    if matched_job:
        print(f"Tracking existing application for {req.company}")
        update_job(
            matched_job["job_id"],
            status="applied",
            applied_date=datetime.now().isoformat()
        )
    else:
        print(f"Tracking new application for {req.company}")
        job_data = {
            "job_id": f"job_{int(datetime.now().timestamp())}",
            "company": req.company,
            "title": "Applied Role",
            "apply_link": req.job_url,
            "status": "applied",
            "applied_date": datetime.now().isoformat(),
            "resume_path": req.generated_resume_path or "references/main.pdf",
            "source": "organic"
        }
        add_job(job_data)
        
    try:
        sync_db_to_excel()
    except Exception as e:
        print(f"Failed to sync excel: {e}")

    # 2. Cleanup temp resume
    if req.is_generated and req.generated_resume_path:
        path = Path(req.generated_resume_path)
        if path.exists():
            try:
                # We often have the whole folder created by run_tailor
                # But for now we'll just delete the file specified or the parent folder
                parent = path.parent
                if "applications" in str(parent):
                    # For safety, only remove if in outputs/applications
                    import shutil
                    shutil.rmtree(parent)
                    print(f"Cleaned up tailored resume folder: {parent}")
            except Exception as e:
                print(f"Error cleaning up temp files: {e}")

    return {"status": "success", "message": "Job tracked and cleanup complete"}

@router.post("/{filename}")
def update_profile(filename: str, payload: ProfileUpdate):
    if not payload.content:
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILE_DIR / filename
    if path.suffix != ".md":
        raise HTTPException(status_code=400, detail="Only .md files allowed")
        
    path.write_text(payload.content, encoding="utf-8")
    return {"status": "success", "filename": filename}
