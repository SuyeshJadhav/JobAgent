import csv
import json
import os
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent
DB_CSV_PATH = ROOT_DIR / "tracked_jobs.csv"
OUTPUTS_DIR = ROOT_DIR / "outputs" / "applications"

FIELDNAMES = [
    "job_id", "company", "title", "status", "score", "reason",
    "apply_link", "source", "location", "found_at", "applied_date",
    "resume_path", "cover_letter_path", "notes", "last_updated"
]

def init_csv():
    if not DB_CSV_PATH.exists():
        with open(DB_CSV_PATH, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()

def _read_csv() -> list[dict]:
    init_csv()
    jobs = []
    with open(DB_CSV_PATH, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("score"):
                try: 
                    row["score"] = int(float(row["score"]))
                except ValueError:
                    row["score"] = 0
            jobs.append(row)
    return jobs

def _write_csv(jobs: list[dict]):
    with open(DB_CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for job in jobs:
            row = {k: job.get(k, "") for k in FIELDNAMES}
            writer.writerow(row)

def save_job_details(job: dict) -> str:
    job_id = job.get("job_id")
    if not job_id:
        return ""
        
    job_dir = OUTPUTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    details_path = job_dir / "job_details.json"
    
    details = {
        "job_id": job_id,
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "description": job.get("description", ""),
        "score": job.get("score", 0),
        "reason": job.get("reason", ""),
        "apply_link": job.get("apply_link", ""),
        "source": job.get("source", "simplify"),
        "found_at": job.get("found_at", datetime.now().isoformat())
    }
    
    with open(details_path, "w", encoding="utf-8") as f:
        json.dump(details, f, indent=4)
        
    return str(details_path)

def load_job_details(job_id: str) -> dict | None:
    details_path = OUTPUTS_DIR / job_id / "job_details.json"
    if details_path.exists():
        with open(details_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def get_jobs(status: str = None) -> list[dict]:
    jobs = _read_csv()
    if status:
        return [j for j in jobs if j.get("status") == status]
    return jobs

def get_job_by_id(job_id: str) -> dict | None:
    jobs = _read_csv()
    for j in jobs:
        if j.get("job_id") == job_id:
            return j
    return None

def add_job(job: dict) -> str:
    jobs = _read_csv()
    job_id = job.get("job_id", "")
    
    for existing in jobs:
        if existing.get("job_id") == job_id:
            return job_id

    new_job = {
        "job_id": job_id,
        "company": job.get("company", ""),
        "title": job.get("title", ""),
        "status": job.get("status", "found"),
        "score": int(job.get("score", 0)),
        "reason": job.get("reason", "")[:2000],
        "apply_link": job.get("apply_link", ""),
        "source": job.get("source", "simplify"),
        "location": job.get("location", ""),
        "found_at": job.get("found_at", datetime.now().isoformat()),
        "applied_date": "",
        "resume_path": job.get("resume_path", ""),
        "cover_letter_path": job.get("cover_letter_path", ""),
        "notes": job.get("notes", ""),
        "last_updated": datetime.now().isoformat()    
    }
    
    jobs.append(new_job)
    try:
        _write_csv(jobs)
        return job_id
    except PermissionError:
        print(f"Error: Could not write to {DB_CSV_PATH.name}. Is it open in Excel?")
        return ""

def update_status(job_id: str, status: str, **kwargs):
    jobs = _read_csv()
    updated = False
    
    for j in jobs:
        if j.get("job_id") == job_id:
            j["status"] = status
            j["last_updated"] = datetime.now().isoformat()
            
            if status in ["applied", "interviewing", "rejected", "offer"]:
                j["applied_date"] = datetime.now().date().isoformat()
                
            for k, v in kwargs.items():
                if k == "ResumePath": j["resume_path"] = str(v)
                elif k == "CoverLetterPath": j["cover_letter_path"] = str(v)
                elif k == "Notes": j["notes"] = str(v)
                    
            updated = True
            break
            
    if updated:
        try:
            _write_csv(jobs)
        except PermissionError:
            print(f"Error: Could not update {DB_CSV_PATH.name}. Is it open in Excel?")
