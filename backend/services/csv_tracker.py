import csv
import json
from pathlib import Path
from datetime import datetime

CSV_PATH = Path("tracked_jobs.csv")

COLUMNS = [
    "job_id", "company", "title", "status",
    "score", "reason", "apply_link", "source",
    "location", "found_at", "applied_date",
    "resume_path", "cover_letter_path",
    "notes", "last_updated"
]

STATUS_ORDER = [
    "found", "shortlisted", "tailored",
    "applied", "interviewing", "rejected", "offer",
    "skipped", "failed"
]

def _ensure_csv():
    """Create CSV with headers if it doesn't exist"""
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="", 
                  encoding="utf-8") as f:
            writer = csv.DictWriter(f, 
                                    fieldnames=COLUMNS)
            writer.writeheader()

def _read_all() -> list[dict]:
    """Read all rows from CSV"""
    _ensure_csv()
    with open(CSV_PATH, "r", newline="",
              encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)

def _write_all(rows: list[dict]):
    """Overwrite entire CSV with rows"""
    _ensure_csv()
    with open(CSV_PATH, "w", newline="",
              encoding="utf-8") as f:
        writer = csv.DictWriter(f, 
                                fieldnames=COLUMNS,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

def add_job(job: dict) -> bool:
    """
    Add job to CSV. Skip if job_id already exists.
    Returns True if added, False if duplicate.
    """
    rows = _read_all()
    existing_ids = {r["job_id"] for r in rows}
    
    if job["job_id"] in existing_ids:
        return False
    
    row = {col: job.get(col, "") for col in COLUMNS}
    row["last_updated"] = datetime.now().isoformat()
    
    rows.append(row)
    _write_all(rows)
    return True

def update_job(job_id: str, **kwargs) -> bool:
    """
    Update fields for a specific job_id.
    Returns True if found and updated, False if not found.
    """
    rows = _read_all()
    updated = False
    
    for row in rows:
        if row["job_id"] == job_id:
            # Enforce forward-only status transitions
            if "status" in kwargs:
                new_status = kwargs["status"]
                current_status = row["status"]
                if not _can_transition(
                    current_status, new_status
                ):
                    print(
                        f"[WARN] Invalid transition: "
                        f"{current_status} → {new_status}"
                    )
                    kwargs.pop("status")
            
            # Payload Starvation Defensive Guard
            eval_status = kwargs.get("status", row.get("status", ""))
            eval_score = int(kwargs.get("score", row.get("score", 0)))
            if eval_status in ["rejected", "skipped"] or eval_score < 6:
                kwargs.pop("description", None)
                kwargs.pop("llm_reasoning", None)
                if "description" in row:
                    del row["description"]
                if "llm_reasoning" in row:
                    del row["llm_reasoning"]
            
            for key, val in kwargs.items():
                if key in COLUMNS:
                    row[key] = val
            row["last_updated"] = datetime.now().isoformat()
            updated = True
            break
    
    if updated:
        _write_all(rows)
    return updated

def get_jobs(status: str = None) -> list[dict]:
    """
    Get all jobs, optionally filtered by status.
    """
    rows = _read_all()
    if status:
        rows = [r for r in rows 
                if r["status"] == status]
    return rows

def get_job_by_id(job_id: str) -> dict | None:
    """Get single job by job_id"""
    rows = _read_all()
    for row in rows:
        if row["job_id"] == job_id:
            return row
    return None

def get_stats() -> dict:
    """Return counts grouped by status"""
    rows = _read_all()
    stats = {s: 0 for s in STATUS_ORDER}
    for row in rows:
        status = row.get("status", "")
        if status in stats:
            stats[status] += 1
    stats["total"] = len(rows)
    return stats

def _can_transition(current: str, new: str) -> bool:
    """
    Enforce forward-only status transitions.
    Side branches (skipped, failed) allowed anytime.
    """
    SIDE_BRANCHES = {"skipped", "failed", 
                     "manual_needed"}
    if new in SIDE_BRANCHES:
        return True
    if current in SIDE_BRANCHES:
        return True
    try:
        return (STATUS_ORDER.index(new) >= 
                STATUS_ORDER.index(current))
    except ValueError:
        return True

def save_job_details(job: dict) -> str:
    """
    Save full JD text to local JSON.
    CSV stores path, not full description.
    Returns path to saved file.
    """
    # Guard clause: only save details for shortlisted jobs (score >= 6)
    if job.get('score', 0) < 6 or job.get('status') == 'rejected':
        return ""

    folder = Path("outputs/applications") / job["job_id"]
    folder.mkdir(parents=True, exist_ok=True)
    
    details_path = folder / "job_details.json"
    with open(details_path, "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)
    
    return str(details_path)

def load_job_details(job_id: str) -> dict | None:
    """Load full JD from local JSON by job_id"""
    details_path = (
        Path("outputs/applications") / 
        job_id / 
        "job_details.json"
    )
    if not details_path.exists():
        return None
    with open(details_path, encoding="utf-8") as f:
        return json.load(f)
