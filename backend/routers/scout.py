import asyncio
from backend.services.jd_scraper import scrape_full_jd
from fastapi import APIRouter, BackgroundTasks
from pathlib import Path

from backend.services.job_sources import fetch_simplify_jobs
from backend.services.scorer import score_job
from backend.services.csv_tracker import (
    add_job, get_jobs, get_job_by_id,
    save_job_details, load_job_details, update_job
)
from backend.services.llm_client import get_settings
from backend.routers.tailor import run_tailor_endpoint

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

async def _process_jobs_bg(new_jobs: list[dict], profile: dict, threshold: int):
    semaphore = asyncio.Semaphore(3)

    async def process_single_job(job):
        async with semaphore:
            try:
                # Scrape JD
                jd_text = await scrape_full_jd(job['apply_link'])
                if jd_text:
                    job['description'] = jd_text
                    save_job_details(job)
                else:
                    print(f"Scraping returned no text for {job['job_id']}")
                    job['status'] = "rejected"
                    update_job(job["job_id"], status="rejected", score=0, reason="Scrape failed")
                    return

                # Score Job
                score, reason = score_job(job, profile)
                job["score"] = score
                job["reason"] = reason
                
                if score >= threshold:
                    job["status"] = "shortlisted"
                    update_job(job["job_id"], status="shortlisted", score=score, reason=reason)
                    save_job_details(job)
                    try:
                        run_tailor_endpoint(job["job_id"])
                    except Exception as e:
                        print(f"Error running tailor for job {job['job_id']}: {e}")
                else:
                    job["status"] = "rejected"
                    update_job(job["job_id"], status="rejected", score=score, reason=reason)
                    save_job_details(job)
            except Exception as e:
                print(f"Error processing job in bg: {e}")
                job['status'] = "rejected"
                update_job(job["job_id"], status="rejected", score=0, reason=f"Error processing: {e}")

    await asyncio.gather(*[process_single_job(job) for job in new_jobs])

@router.post("/run")
def run_scout(background_tasks: BackgroundTasks):
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
        "shortlisted": "Processing in background",
        "skipped": "Processing in background",
        "new": 0,
        "duplicate": 0
    }
    
    new_jobs = []
    
    # 4. For each job
    for job in raw_jobs:
        job_id = job.get("job_id")
        
        # a. Check if already exists
        existing = get_job_by_id(job_id)
        if existing:
            summary["duplicate"] += 1
            continue
            
        summary["new"] += 1
        
        # Save initially as found
        job["status"] = "found"
        job["score"] = 0
        job["reason"] = ""
        add_job(job)
        save_job_details(job)
        new_jobs.append(job)
            
    if new_jobs:
        background_tasks.add_task(_process_jobs_bg, new_jobs, profile, threshold)
        
    summary["message"] = f"Triggered background scoring for {len(new_jobs)} new jobs."
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
