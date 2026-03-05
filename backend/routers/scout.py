import asyncio
from backend.services.jd_scraper import scrape_full_jd
from backend.utils.text_cleaner import trim_jd_text, contains_bad_title, contains_dealbreakers, is_auto_shortlist_title, is_target_location
from fastapi import APIRouter, BackgroundTasks
from pathlib import Path

from backend.services.job_sources import fetch_simplify_jobs
from backend.services.scorer import score_job
from backend.services.csv_tracker import (
    add_job, get_jobs, get_job_by_id,
    save_job_details, load_job_details, update_job
)
from backend.services.excel_formatter import sync_csv_to_excel
from backend.services.profile_manager import parse_candidate_profile
from backend.services.llm_client import get_settings

router = APIRouter(prefix="/api/scout", tags=["scout"])

async def _process_jobs_bg(new_jobs: list[dict], profile: dict, threshold: int):
    semaphore = asyncio.Semaphore(3)

    async def process_single_job(job):
        async with semaphore:
            try:
                # Gate 1: Fast-fail on irrelevant titles
                bad_title_match = contains_bad_title(job.get('title'))
                if bad_title_match:
                    reason = f"Rejected: Irrelevant title match ({bad_title_match})"
                    update_job(job["job_id"], status="rejected", score=1, reason=reason)
                    print(f"[SKIP] {job.get('title')} - {job.get('company')} (Title Blocklist: {bad_title_match})")
                    return
                    
                # Gate 1.5: Fast-fail on Non-US locations
                loc_str = job.get('location', '')
                if not is_target_location(loc_str):
                    reason = f"Rejected: Non-US Location ({loc_str})"
                    update_job(job["job_id"], status="rejected", score=1, reason=reason)
                    print(f"[SKIP] {job.get('title')} - {job.get('company')} (Location: {loc_str})")
                    return

                # Gate 2: Web Scrape
                jd_text = await scrape_full_jd(job['apply_link'])
                if not jd_text or jd_text == "SCRAPE_BLOCKED":
                    reason = "Scrape blocked by bot protection" if jd_text == "SCRAPE_BLOCKED" else "Scrape failed to find JD text"
                    update_job(job["job_id"], status="rejected", score=0, reason=reason)
                    print(f"[FAIL] {job.get('title')} - {job.get('company')} ({reason})")
                    return

                # Gate 3: Sanitization
                jd_text = trim_jd_text(jd_text)
                job['description'] = jd_text

                # Check for VIP Auto-Shortlist Override
                is_vip = is_auto_shortlist_title(job.get('title'))
                
                if is_vip:
                    score = 10
                    reason = "Auto-Shortlisted (Protected Title)"
                else:
                    # Gate 4: Dealbreaker evaluation
                    db_match = contains_dealbreakers(jd_text)
                    if db_match:
                        reason = f"Rejected: Found dealbreaker terms in JD ({db_match})"
                        update_job(job["job_id"], status="rejected", score=1, reason=reason)
                        print(f"[SKIP] {job.get('title')} - {job.get('company')} (Dealbreaker: {db_match})")
                        return

                    # Gate 5: LLM Scoring
                    score, reason = score_job(job, profile)
                
                job["score"] = score
                job["reason"] = reason
                
                # Gate 6: Storage Delegation (Phase 1 stops here)
                if score >= threshold:
                    job["status"] = "shortlisted"
                    update_job(job["job_id"], status="shortlisted", score=score, reason=reason)
                    save_job_details(job) # Storage enforced inside this call
                    print(f"[WIN]  {job.get('title')} - {job.get('company')} (Score: {score}/10)")
                else:
                    job["status"] = "rejected"
                    update_job(job["job_id"], status="rejected", score=score, reason=reason)
                    print(f"[REJ]  {job.get('title')} - {job.get('company')} (Score: {score}/10)")

            except Exception as e:
                print(f"[ERROR] processing {job.get('job_id')}: {e}")
                update_job(job["job_id"], status="rejected", score=0, reason=f"Internal error: {e}")

    await asyncio.gather(*[process_single_job(job) for job in new_jobs])
    try:
        sync_csv_to_excel("tracked_jobs.csv")
        print("[SYNC] Successfully synced tracked_jobs.csv to Excel.")
    except Exception as e:
        print(f"[SYNC ERROR] Failed to sync to Excel: {e}")

@router.post("/run")
def run_scout(background_tasks: BackgroundTasks):
    settings = get_settings()
    job_types = settings.get("job_types", ["internship"])
    threshold = int(settings.get("score_threshold", 6))
    
    # Delegate profile parsing
    profile_path = Path(__file__).parent.parent.parent / "references" / "candidate_profile.md"
    profile = parse_candidate_profile(profile_path)
    
    # Fetch initial batch
    raw_jobs = fetch_simplify_jobs(job_types)
    
    new_jobs = []
    for job in raw_jobs:
        if not get_job_by_id(job.get("job_id")):
            job.update({"status": "found", "score": 0, "reason": ""})
            add_job(job)
            new_jobs.append(job)
            
    if new_jobs:
        background_tasks.add_task(_process_jobs_bg, new_jobs, profile, threshold)
        
    return {
        "found": len(raw_jobs),
        "new": len(new_jobs),
        "message": f"Triggered knockout pipeline for {len(new_jobs)} jobs."
    }

@router.get("/jobs")
def get_scout_jobs(status: str = None):
    return get_jobs(status=status)

@router.get("/jobs/{job_id}")
def get_job_details_api(job_id: str):
    job_data = get_job_by_id(job_id)
    if not job_data:
        return {}
        
    local_details = load_job_details(job_id)
    if local_details:
        job_data["description"] = local_details.get("description", "")
        
    return job_data


# ─── Organic Tracking (from extension) ──────────────────────────────────

from pydantic import BaseModel
from typing import Optional
import hashlib

class OrganicTrackRequest(BaseModel):
    url: str
    title: Optional[str] = ""
    company: Optional[str] = ""
    page_text: Optional[str] = ""

from backend.utils.url_matcher import find_job_by_url, normalize_url

@router.get("/check_url")
def check_url_tracked(url: str):
    """Check if a URL is already tracked. Returns the job row if found, 404 otherwise."""
    jobs = get_jobs()
    matched = find_job_by_url(jobs, url)
    if matched:
        return {"tracked": True, "job": matched}
    return {"tracked": False}

@router.post("/organic")
def organic_track_and_score(payload: OrganicTrackRequest):
    """
    Organic tracking: the extension sends us the page URL, title, company,
    and the full page text. We sanitize, score, and add to the tracker in
    one synchronous call, then return the result immediately.
    """
    # 1. Generate a stable job_id from the URL
    norm_url = normalize_url(payload.url)
    job_id = hashlib.md5(norm_url.encode()).hexdigest()[:12]

    # 2. Check for duplicate
    existing = get_job_by_id(job_id)
    if existing:
        return {
            "status": "duplicate",
            "job_id": job_id,
            "score": int(existing.get("score", 0)),
            "job_status": existing.get("status", ""),
            "message": "Job already tracked."
        }

    # 3. Sanitize page text into a JD
    jd_text = trim_jd_text(payload.page_text) if payload.page_text else ""

    # 4. Build job dict
    job = {
        "job_id": job_id,
        "title": payload.title or "Unknown Title",
        "company": payload.company or "Unknown Company",
        "apply_link": payload.url,
        "source": "organic",
        "location": "",
        "status": "found",
        "score": 0,
        "reason": "",
        "description": jd_text,
    }

    # 5. Add to CSV
    add_job(job)

    # 6. Score
    settings = get_settings()
    threshold = int(settings.get("score_threshold", 6))
    profile_path = Path(__file__).parent.parent.parent / "references" / "candidate_profile.md"
    profile = parse_candidate_profile(profile_path)

    score, reason = score_job(job, profile)
    job["score"] = score
    job["reason"] = reason

    if score >= threshold:
        job["status"] = "shortlisted"
        update_job(job_id, status="shortlisted", score=score, reason=reason)
        save_job_details(job)
        print(f"[ORGANIC WIN]  {job.get('title')} - {job.get('company')} (Score: {score}/10)")
    else:
        job["status"] = "rejected"
        update_job(job_id, status="rejected", score=score, reason=reason)
        print(f"[ORGANIC REJ]  {job.get('title')} - {job.get('company')} (Score: {score}/10)")

    # 7. Sync to Excel
    try:
        sync_csv_to_excel("tracked_jobs.csv")
    except Exception as e:
        print(f"[SYNC ERROR] {e}")

    return {
        "status": "tracked",
        "job_id": job_id,
        "score": score,
        "reason": reason,
        "job_status": job["status"],
        "message": f"Job scored {score}/10 — {'shortlisted' if score >= threshold else 'rejected'}."
    }
