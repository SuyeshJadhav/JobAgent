from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
from backend.services.sheets_manager import GoogleSheetsManager

router = APIRouter(tags=["Tracking"])
sheets_manager = GoogleSheetsManager()

SAVED_JDS_DIR = Path(__file__).parent.parent / "saved_jds"

class TrackJobPayload(BaseModel):
    title: str
    company: str
    url: str
    job_description: str

def safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()

@router.post("/track_job")
def track_job(payload: TrackJobPayload):
    try:
        date_added = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheets_manager.append_job_row(
            title=payload.title,
            company=payload.company,
            url=payload.url,
            status="Saved",
            date_added=date_added
        )
        
        SAVED_JDS_DIR.mkdir(parents=True, exist_ok=True)
        safe_company = safe_filename(payload.company)
        safe_title = safe_filename(payload.title)
        filename = f"{safe_company}_{safe_title}.txt"
        file_path = SAVED_JDS_DIR / filename
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(payload.job_description)
            
        return {"status": "success", "message": "Job tracked successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
