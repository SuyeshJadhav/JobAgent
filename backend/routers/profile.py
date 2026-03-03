import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.profile_rag import fill_field

router = APIRouter(prefix="/api/profile", tags=["profile"])
PROFILE_DIR = Path(__file__).parent.parent.parent / "profile"

class ProfileUpdate(BaseModel):
    content: str

class FillRequest(BaseModel):
    fields: list[str]
    job_url: str = ""
    company: str = ""

@router.get("")
def get_all_profiles():
    if not PROFILE_DIR.exists():
        return {}
    
    results = {}
    for f in PROFILE_DIR.glob("*.md"):
        results[f.name] = f.read_text(encoding="utf-8")
    return results

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

@router.post("/fill")
def fill_application_fields(req: FillRequest):
    """Bridge for the browser extension to autofill forms via Profile RAG."""
    results = {}
    job_context = f"{req.company} - {req.job_url}"
    
    for field in req.fields:
        val = fill_field(field_name=field, field_context="", job_context=job_context)
        results[field] = val
        
    return results
