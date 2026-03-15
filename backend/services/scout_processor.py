import asyncio
import json
from pathlib import Path
from datetime import datetime
from backend.services.jd_scraper import scrape_full_jd
from backend.utils.text_cleaner import trim_jd_text, contains_bad_title, contains_dealbreakers, is_auto_shortlist_title, is_target_location, is_garbage_metadata
from backend.services.scorer import score_job
from backend.services.db_tracker import (
    add_job, get_jobs, get_job_by_id,
    save_job_details, update_job
)
from backend.services.profile_manager import parse_candidate_profile
from backend.services.llm_client import get_settings
from backend.utils.url_matcher import generate_deterministic_job_id

class ScoutProcessor:
    """
    The core service orchestrator for the job scouting pipeline.
    
    Responsibilities:
    1. Background processing of newly found jobs (Scraping, Scoring, Tracking).
    2. Handling 'organic' tracking requests from the browser extension.
    3. Managing the candidate profile context.
    4. Synchronizing the internal database (tracked_jobs.db) with the external Excel tracker.
    """
    def __init__(self):
        self.settings = get_settings()
        self.threshold = int(self.settings.get("score_threshold", 6))
        self.profile_path = Path(__file__).parent.parent.parent / "references" / "candidate_profile.md"
        self._profile = None

    @property
    def profile(self):
        """Lazy loader for the candidate profile to avoid unnecessary file I/O on every init."""
        if self._profile is None:
            self._profile = parse_candidate_profile(self.profile_path)
        return self._profile

    async def process_jobs_bg(self, new_jobs: list[dict]):
        """
        Asynchronous background task to process a batch of newly discovered jobs.
        Follows a linear 'Gate' pattern:
        1. Title/Location Filtering
        2. Web Scraping
        3. Text Sanitization
        4. LLM Scoring
        5. Database Update & Excel Sync
        """
        semaphore = asyncio.Semaphore(3) # Limit concurrency to avoid rate limits/bot detection

        async def _process_single(job):
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

                    # Check for VIP Auto-Shortlist Override (e.g. Intern roles)
                    is_vip = is_auto_shortlist_title(job.get('title'))
                    
                    if is_vip:
                        score = 10
                        reason = "Auto-Shortlisted (Protected Title)"
                    else:
                        # Gate 4: Dealbreaker evaluation (e.g. No TS/SCI)
                        db_match = contains_dealbreakers(jd_text)
                        if db_match:
                            reason = f"Rejected: Found dealbreaker terms in JD ({db_match})"
                            update_job(job["job_id"], status="rejected", score=1, reason=reason)
                            print(f"[SKIP] {job.get('title')} - {job.get('company')} (Dealbreaker: {db_match})")
                            return

                        # Gate 5: LLM Scoring
                        result = score_job(job, self.profile)
                        score, reason = result["score"], result["reasoning"]
                        
                        # Fix garbage metadata using LLM-extracted values
                        if is_garbage_metadata(job.get("company", ""), job.get("title", "")):
                            if result.get("company"):
                                job["company"] = result["company"]
                            if result.get("title"):
                                job["title"] = result["title"]
                            update_job(job["job_id"], company=job["company"], title=job["title"])
                            print(f"[FIX]  Corrected metadata → {job['company']} - {job['title']}")
                    
                    job["score"] = score
                    job["reason"] = reason
                    
                    # Final determination
                    if score >= self.threshold:
                        job["status"] = "shortlisted"
                        update_job(job["job_id"], status="shortlisted", score=score, reason=reason)
                        print(f"[WIN]  {job.get('title')} - {job.get('company')} (Score: {score}/10)")
                    else:
                        job["status"] = "rejected"
                        update_job(job["job_id"], status="rejected", score=score, reason=reason)
                        print(f"[REJ]  {job.get('title')} - {job.get('company')} (Score: {score}/10)")
                    
                    # Always save details to allow manual tailoring overrides
                    save_job_details(job)

                except Exception as e:
                    print(f"[ERROR] processing {job.get('job_id')}: {e}")
                    update_job(job["job_id"], status="rejected", score=0, reason=f"Internal error: {e}")

        await asyncio.gather(*[_process_single(job) for job in new_jobs])

    def track_organic_job(self, url: str, title: str = None, company: str = None, page_text: str = None) -> dict:
        """
        Processes a single job found 'organically' (via browser extension).
        If the job is already tracked, it performs an 'Upsert' (updating core metadata).
        
        Args:
            url (str): The job posting URL.
            title (str): Job title.
            company (str): Company name.
            page_text (str): Full text scraped from the browser page.
            
        Returns:
            dict: Status summary for the frontend.
        """
        job_id = generate_deterministic_job_id(company, url)
        jd_text = trim_jd_text(page_text) if page_text else ""
        
        existing = get_job_by_id(job_id)
        if existing:
            # Update existing job data with fresh extension info
            updated_job = dict(existing)
            if title: updated_job['title'] = title
            if company: updated_job['company'] = company
            updated_job['description'] = jd_text
            
            update_job(job_id, title=updated_job['title'], company=updated_job['company'])
            
            # Always save updated details to allow manual tailoring overrides
            save_job_details(updated_job)
                
            print(f"[UPSERT] Updated existing tracked job: {updated_job['title']} - {updated_job['company']}")

            
            return {
                "status": "upserted",
                "job_id": job_id,
                "score": int(existing.get("score", 0)),
                "job_status": existing.get("status", ""),
                "message": "Job already tracked (data updated)."
            }

        # Create new job record
        job = {
            "job_id": job_id,
            "title": title or "Unknown Title",
            "company": company or "Unknown Company",
            "apply_link": url,
            "source": "organic",
            "location": "",
            "status": "found",
            "score": 0,
            "reason": "",
            "description": jd_text,
        }
        add_job(job)

        # Single-pass scoring for the organic find
        result = score_job(job, self.profile)
        score, reason = result["score"], result["reasoning"]
        
        # Fix garbage metadata using LLM-extracted values
        if is_garbage_metadata(job.get("company", ""), job.get("title", "")):
            if result.get("company"):
                job["company"] = result["company"]
                update_job(job_id, company=job["company"])
            if result.get("title"):
                job["title"] = result["title"]
                update_job(job_id, title=job["title"])
            print(f"[FIX]  Corrected metadata → {job['company']} - {job['title']}")
        
        job["score"] = score
        job["reason"] = reason

        if score >= self.threshold:
            job["status"] = "shortlisted"
            update_job(job_id, status="shortlisted", score=score, reason=reason)
            print(f"[ORGANIC WIN]  {job.get('title')} - {job.get('company')} (Score: {score}/10)")
        else:
            job["status"] = "rejected"
            update_job(job_id, status="rejected", score=score, reason=reason)
            print(f"[ORGANIC REJ]  {job.get('title')} - {job.get('company')} (Score: {score}/10)")

        # Always save details to allow manual tailoring overrides
        save_job_details(job)


        return {
            "status": "tracked",
            "job_id": job_id,
            "score": score,
            "reason": reason,
            "job_status": job["status"],
            "message": f"Job scored {score}/10 — {'shortlisted' if score >= self.threshold else 'rejected'}."
        }
