from pathlib import Path
from fastapi import APIRouter

from backend.services.job_sources import fetch_simplify_jobs
from backend.services.scorer import score_job
from backend.services.local_tracker import add_job, get_jobs, get_job_by_id, save_job_details, load_job_details
from backend.services.llm_client import get_settings

router = APIRouter(prefix="/api/scout", tags=["scout"])

def _parse_candidate_profile(filepath: Path) -> dict:
    profile = {
        "target_roles": [],
        "skills": [],
        "experience_level": "",
        "preferences": []
    }
    if not filepath.exists():
        return profile
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    current_section = None
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("## "):
            current_section = line[3:].strip()
            continue
            
        if not line or not line.startswith("- "):
            continue
            
        value = line[2:].strip()
        if current_section == "Background":
            profile["skills"].append(value)
            if "Degree:" in value or "Experience:" in value:
                profile["experience_level"] += value + "; "
        elif current_section == "Target Roles":
            profile["target_roles"].append(value)
        elif current_section == "Preferences":
            profile["preferences"].append(value)
            
    # Format for scorer
    return {
        "target_roles": ", ".join(profile["target_roles"]),
        "skills": " | ".join(profile["skills"]),
        "experience_level": profile["experience_level"],
        "preferences": " | ".join(profile["preferences"])
    }

@router.post("/run")
def run_scout():
    settings = get_settings()
    job_types = settings.get("job_types", ["internship"])
    threshold = int(settings.get("score_threshold", 6))
    
    # 2. Read candidate profile
    profile_path = Path(__file__).parent.parent.parent / "references" / "candidate_profile.md"
    profile = _parse_candidate_profile(profile_path)
    
    # 3. Fetch jobs
    raw_jobs = fetch_simplify_jobs(job_types)
    
    summary = {
        "found": len(raw_jobs),
        "shortlisted": 0,
        "skipped": 0,
        "new": 0,
        "duplicate": 0
    }
    
    processed_jobs = []
    
    # 4. For each job
    for job in raw_jobs:
        job_id = job.get("job_id")
        
        # a. Check if already exists
        existing = get_job_by_id(job_id)
        if existing:
            summary["duplicate"] += 1
            continue
            
        summary["new"] += 1
        
        # b. Score job
        score, reason = score_job(job, profile)
        job["score"] = score
        job["reason"] = reason
        
        # c. Set status
        if score >= threshold:
            job["status"] = "shortlisted"
            summary["shortlisted"] += 1
        else:
            job["status"] = "skipped"
            summary["skipped"] += 1
            
        # d. Save local details (which includes full description)
        save_job_details(job)
        
        # We don't want to push full description to Notion API, it's too long
        # But we want to keep it in our response for processed_jobs, or pop it before Notion
        # get_job_by_id handles it by only caring about what we feed it
        notion_id = add_job(job)
        if notion_id:
            job["notion_id"] = notion_id
            
        processed_jobs.append(job)
        
    summary["jobs_processed"] = processed_jobs
    return summary

@router.get("/jobs")
def get_scout_jobs(status: str = None):
    return get_jobs(status=status)

@router.get("/jobs/{job_id}")
def get_job_details_api(job_id: str):
    notion_job = get_job_by_id(job_id)
    if not notion_job:
        return {}
        
    local_details = load_job_details(job_id)
    if local_details:
        notion_job["description"] = local_details.get("description", "")
        
    return notion_job
