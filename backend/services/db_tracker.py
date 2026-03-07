import sqlite3
import json
import re
from pathlib import Path
from datetime import datetime

# Path to the new SQLite database
DB_PATH = Path("backend/tracked_jobs.db")
# Fallback if running outside backend/
if not Path("backend").exists():
    DB_PATH = Path("tracked_jobs.db")

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

def get_db_connection():
    """Returns a SQLite connection. Thread-safe when used locally."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row  # Enables dict-like access
    return conn

def _ensure_db():
    """Create the jobs table if it doesn't exist."""
    query = '''
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        company TEXT,
        title TEXT,
        status TEXT,
        score INTEGER,
        reason TEXT,
        apply_link TEXT,
        source TEXT,
        location TEXT,
        found_at TEXT,
        applied_date TEXT,
        resume_path TEXT,
        cover_letter_path TEXT,
        notes TEXT,
        last_updated TEXT
    )
    '''
    with get_db_connection() as conn:
        conn.execute(query)
        conn.commit()

# Ensure the DB schema matches on import
_ensure_db()

def _can_transition(current: str, new: str) -> bool:
    """
    Enforce forward-only status transitions.
    Side branches (skipped, failed) allowed anytime.
    """
    SIDE_BRANCHES = {"skipped", "failed", "manual_needed"}
    if new in SIDE_BRANCHES:
        return True
    if current in SIDE_BRANCHES:
        return True
    try:
        return STATUS_ORDER.index(new) >= STATUS_ORDER.index(current)
    except ValueError:
        return True

def add_job(job: dict) -> bool:
    """
    Add job to SQLite DB. Skip if job_id already exists.
    Returns True if added, False if duplicate.
    """
    job_id = job.get("job_id")
    if not job_id:
        return False
        
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Check if exists
        cursor.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,))
        if cursor.fetchone():
            return False
            
        # Prepare row data mapping directly to COLUMNS
        row_data = {col: job.get(col, "") for col in COLUMNS}
        
        # Ensure score is numeric
        try:
            row_data["score"] = int(row_data["score"])
        except (ValueError, TypeError):
            row_data["score"] = 0
            
        row_data["last_updated"] = datetime.now().isoformat()
        
        placeholders = ', '.join(['?' for _ in COLUMNS])
        columns_sql = ', '.join(COLUMNS)
        
        values = [row_data[col] for col in COLUMNS]
        
        cursor.execute(f"INSERT INTO jobs ({columns_sql}) VALUES ({placeholders})", values)
        conn.commit()
    
    return True

def update_job(job_id: str, **kwargs) -> bool:
    """
    Update fields for a specific job_id in SQLite.
    Returns True if found and updated, False if not found.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        
        if not row:
            return False
            
        row_dict = dict(row)
        
        # Enforce forward-only status transitions
        if "status" in kwargs:
            new_status = kwargs["status"]
            current_status = row_dict["status"]
            if not _can_transition(current_status, new_status):
                print(f"[WARN] Invalid transition: {current_status} → {new_status}")
                kwargs.pop("status")
        
        # Payload Starvation Defensive Guard
        eval_status = kwargs.get("status", row_dict.get("status", ""))
        eval_score = int(kwargs.get("score", row_dict.get("score", 0)))
        if eval_status in ["rejected", "skipped"] or eval_score < 6:
            kwargs.pop("description", None)
            kwargs.pop("llm_reasoning", None)
            
        update_fields = []
        update_values = []
        
        for key, val in kwargs.items():
            if key in COLUMNS:
                update_fields.append(f"{key} = ?")
                if key == "score":
                    try:
                        val = int(val)
                    except (ValueError, TypeError):
                        val = 0
                update_values.append(val)
                
        if not update_fields:
            return True # Nothing valid to update
            
        update_fields.append("last_updated = ?")
        update_values.append(datetime.now().isoformat())
        
        update_values.append(job_id) # For the WHERE clause
        
        sql = f"UPDATE jobs SET {', '.join(update_fields)} WHERE job_id = ?"
        cursor.execute(sql, update_values)
        conn.commit()
        
    return True

def get_jobs(status: str = None) -> list[dict]:
    """
    Get all jobs, optionally filtered by status.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if status:
            cursor.execute("SELECT * FROM jobs WHERE status = ?", (status,))
        else:
            cursor.execute("SELECT * FROM jobs")
            
        return [dict(row) for row in cursor.fetchall()]

def get_job_by_id(job_id: str) -> dict | None:
    """Get single job by job_id"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_stats() -> dict:
    """Return counts grouped by status"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) as count FROM jobs GROUP BY status")
        
        stats = {s: 0 for s in STATUS_ORDER}
        total = 0
        
        for row in cursor.fetchall():
            status = row['status']
            count = row['count']
            if status in stats:
                stats[status] = count
            total += count
            
        stats["total"] = total
        return stats


# --- JSON Detached Storage Mechanisms ---

def _safe_filename(name: str) -> str:
    val = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', str(name))
    return re.sub(r'_+', '_', val)

def _get_readable_job_dir(job: dict) -> Path:
    company = _safe_filename(job.get("company", "Unknown"))
    title = _safe_filename(job.get("title", "Unknown"))
    
    date_str = ""
    found = job.get("found_at", "")
    if found:
        date_str = found[:10]
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        
    job_id = job.get("job_id", "")
    short_id = job_id[:8] if job_id else "NoID"
    
    # Needs to adapt to whether it's running inside backend/ or root
    base = Path("outputs/applications")
    if not base.exists() and Path("../outputs/applications").exists():
        base = Path("../outputs/applications")
        
    return base / f"{company}-{title}-{date_str}-{short_id}"

def save_job_details(job: dict) -> str:
    """
    Save full JD text to local JSON in a human-readable folder.
    Returns path to saved file.
    """
    if job.get('score', 0) < 6 or job.get('status') == 'rejected':
        return ""

    folder = _get_readable_job_dir(job)
    folder.mkdir(parents=True, exist_ok=True)
    
    details_path = folder / "job_details.json"
    with open(details_path, "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)
    
    return str(details_path)

def load_job_details(job_id: str) -> dict | None:
    """Load full JD from local JSON by searching for job_id in directory name"""
    base = Path("outputs/applications")
    if not base.exists() and Path("../outputs/applications").exists():
        base = Path("../outputs/applications")
        
    if not base.exists():
        return None
        
    # 1. Fallback: Check if it was saved under the old raw job_id directory
    legacy_path = base / job_id / "job_details.json"
    if legacy_path.exists():
        with open(legacy_path, encoding="utf-8") as f:
            return json.load(f)

    # 2. Search for readable folders containing the short job_id
    short_id = job_id[:8] if len(job_id) >= 8 else job_id
    for d in base.iterdir():
        if d.is_dir() and short_id in d.name:
            details_path = d / "job_details.json"
            if details_path.exists():
                with open(details_path, encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("job_id") == job_id:
                        return data
                        
    # 3. Fallback: Iterate all to be fully safe
    for d in base.iterdir():
        if d.is_dir():
            details = d / "job_details.json"
            if details.exists():
                try:
                    with open(details, encoding="utf-8") as f:
                        data = json.load(f)
                        if data.get("job_id") == job_id:
                            return data
                except Exception:
                    pass
    return None
    
# --- Migration logic from CSV ---
def migrate_csv_to_db():
    import csv
    csv_path = Path("tracked_jobs.csv")
    if not csv_path.exists() and Path("backend/tracked_jobs.csv").exists():
        csv_path = Path("backend/tracked_jobs.csv")
        
    if not csv_path.exists():
        return # No CSV to migrate
        
    print(f"Migrating {csv_path} to SQLite database...")
    
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        migrated_count = 0
        for row in reader:
            if add_job(row):
                migrated_count += 1
                
    print(f"Migration complete: {migrated_count} jobs migrated to SQLite.")
    
    # Rename CSV to backup
    backup_path = csv_path.with_name(f"{csv_path.name}.backup")
    import os
    if os.path.exists(backup_path):
        os.remove(backup_path)
    os.rename(csv_path, backup_path)
    print(f"Backed up CSV to {backup_path}")

# Run migration automatically if CSV exists
if Path("tracked_jobs.csv").exists() or Path("backend/tracked_jobs.csv").exists():
    _ensure_db()
    migrate_csv_to_db()
