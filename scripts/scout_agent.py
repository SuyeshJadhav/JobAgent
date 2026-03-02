"""
Scout Agent -- finds fresh job listings daily and scores them for role fit.

Usage:
    python scripts/scout_agent.py
    python scripts/scout_agent.py --query "AI Engineer intern"
    python scripts/scout_agent.py --score-only

Pipeline import:
    from scripts.scout_agent import run, score_existing
    run()
    score_existing()

Dependencies:
    pip install python-jobspy openai
"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from utils import check_ollama, llm_call, log, read_score_threshold

# ── Paths ────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "scout_jobs.db"
CANDIDATE_PROFILE = ROOT_DIR / "references" / "candidate_profile.md"

DEFAULT_SCORE_THRESHOLD = 6


# ── Profile helpers ──────────────────────────────────────────
def _load_profile() -> str:
    if CANDIDATE_PROFILE.exists():
        return CANDIDATE_PROFILE.read_text(encoding="utf-8")
    log("WARNING: candidate_profile.md not found. Scoring will lack candidate context.")
    return ""


def _read_queries_from_profile(profile: str) -> list[str]:
    """Extract target role queries from the ## Target Roles section."""
    roles_match = re.search(r"## Target Roles\s*(.*?)(?=##|\Z)", profile, re.DOTALL | re.IGNORECASE)
    if roles_match:
        lines = roles_match.group(1).strip().split("\n")
        return [line.lstrip("-").strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    return []


def _load_blocked_companies(profile: str) -> list[str]:
    match = re.search(r"### Blocked Companies\s*(.*?)(?=(?:###|##|\Z))", profile, re.DOTALL | re.IGNORECASE)
    if match:
        lines = match.group(1).strip().split("\n")
        return [line.lstrip("-").strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    return []


def _load_blocked_keywords(profile: str) -> list[str]:
    match = re.search(r"### Blocked Keywords\s*(.*?)(?=(?:###|##|\Z))", profile, re.DOTALL | re.IGNORECASE)
    if match:
        lines = match.group(1).strip().split("\n")
        return [line.lstrip("-").strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    return []


# ── Database ─────────────────────────────────────────────────
def _init_db() -> None:
    """Create scout_jobs.db and table if they don't exist."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS jobs (
            job_id            TEXT PRIMARY KEY,
            title             TEXT,
            company           TEXT,
            location          TEXT,
            apply_link        TEXT,
            description       TEXT,
            score             INTEGER,
            reason            TEXT,
            found_at          TEXT,
            applied_at        TEXT,
            status            TEXT,
            resume_path       TEXT,
            cover_letter_path TEXT,
            notes             TEXT,
            last_updated      TEXT
        )"""
    )
    conn.commit()
    conn.close()


def _get_db():
    if not DB_PATH.exists():
        _init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _job_exists(job_id: str, title: str = "", company: str = "") -> bool:
    """Check if job already exists to avoid duplicates."""
    conn = _get_db()
    try:
        row = conn.execute("SELECT job_id FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row:
            return True
        if title and company:
            row = conn.execute(
                "SELECT job_id FROM jobs WHERE LOWER(title) = ? AND LOWER(company) = ?",
                (title.lower().strip(), company.lower().strip()),
            ).fetchone()
            if row:
                return True
        return False
    finally:
        conn.close()


def _save_job(job: dict) -> None:
    """Save a new job to DB with status = 'found'."""
    conn = _get_db()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO jobs (job_id, title, company, location, apply_link, "
            "description, found_at, status, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'found', ?)",
            (
                job["job_id"],
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("apply_link", ""),
                job.get("description", ""),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _update_job_score(job_id: str, score: int, reason: str, status: str) -> None:
    """Update job score and status after Scorer runs."""
    conn = _get_db()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            """UPDATE jobs SET score = ?, reason = ?, status = ?, last_updated = ? WHERE job_id = ?""",
            (score, reason, status, now, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def _get_unscored_jobs() -> list[dict]:
    """Return all jobs where score IS NULL (never scored)."""
    conn = _get_db()
    try:
        rows = conn.execute("SELECT job_id, title, company, description FROM jobs WHERE score IS NULL").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── JobSpy Scraper ───────────────────────────────────────────
def _fetch_jobs(query: str) -> list[dict]:
    """Scrape jobs using JobSpy (no API key required)."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        sys.exit("ERROR: jobspy not installed. Run: pip install python-jobspy")

    log(f"Scraping jobs for: '{query}'")
    try:
        df = scrape_jobs(
            site_name=["linkedin"],
            search_term=query,
            location="United States",
            job_type="internship",
            results_wanted=15,
            hours_old=24,
            is_remote=True,
            linkedin_fetch_description=True,
        )
    except Exception as e:
        log(f"JobSpy scrape error: {e}")
        return []

    if df is None or df.empty:
        log("No results returned from JobSpy.")
        return []

    log(f"JobSpy returned {len(df)} results.")
    return df.to_dict("records")


def _format_jobspy_job(raw: dict) -> dict:
    """Map JobSpy DataFrame row to DB schema."""
    title = str(raw.get("title") or "")
    company = str(raw.get("company") or "")

    # Use scraped id if present, else hash title+company+url for stable dedup
    raw_id = str(raw.get("id") or "")
    if not raw_id or raw_id == "nan":
        fingerprint = f"{title}|{company}|{raw.get('job_url', '')}"
        raw_id = hashlib.sha1(fingerprint.encode()).hexdigest()[:16]

    return {
        "job_id": raw_id,
        "title": title,
        "company": company,
        "location": str(raw.get("location") or ""),
        "apply_link": str(raw.get("job_url") or ""),
        "description": str(raw.get("description") or ""),
    }


# ── LLM Scorer ───────────────────────────────────────────────
def _score_job(job: dict, candidate_profile: str, model: str) -> dict:
    """Score a job listing using Ollama based on candidate preferences."""
    system = (
        "You are filtering jobs for a candidate.\n\n"
        f"CANDIDATE PREFERENCES:\n{candidate_profile}\n\n"
        "Score 1-10 based on role fit (NOT resume match).\n"
        "10 = Perfect fit, 6 = Minimum viable fit, 1 = Red flag or completely unrelated.\n"
        'Reply ONLY as valid JSON: {"score": <n>, "reason": "<one sentence>"}\n'
        "Do NOT include markdown backticks around your response."
    )

    user = (
        f"JOB:\n"
        f"Title: {job.get('title')}\n"
        f"Company: {job.get('company')}\n"
        f"Description: {job.get('description', '')[:2000]}\n"
    )

    result = llm_call(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=model,
        temperature=0.1,
    )

    # Clean possible markdown formatting
    result = result.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(result)
    except json.JSONDecodeError:
        log(f"WARNING: Invalid JSON from scorer: {result[:200]}")
        return {"score": 0, "reason": "Failed to parse LLM response"}


def _run_scorer(jobs: list[dict], profile: str, threshold: int, model: str) -> None:
    """Score a list of jobs and update the DB. Shared by run() and score_existing()."""
    log(f"Scoring {len(jobs)} jobs with {model} (threshold={threshold})...")

    for i, job in enumerate(jobs, 1):
        log(f"  [{i}/{len(jobs)}] Scoring: {job['title']} @ {job['company']}")
        score_res = _score_job(job, profile, model)

        score = score_res.get("score", 0)
        reason = score_res.get("reason", "")
        status = "shortlisted" if score >= threshold else "skipped"

        _update_job_score(job["job_id"], score, reason, status)
        log(f"    -> Score: {score} | Status: {status} | Reason: {reason}")


# ===============================================================
#  SCORE-ONLY FUNCTION
# ===============================================================
def score_existing(model: str = "qwen2.5:7b") -> None:
    """
    Score all jobs in the DB where score IS NULL, without re-scraping.
    Use when scout ran successfully but Ollama was not running at the time.
    """
    check_ollama()
    _init_db()

    profile = _load_profile()
    threshold = read_score_threshold(profile)

    jobs = _get_unscored_jobs()
    if not jobs:
        log("No unscored jobs found. All jobs already have a score.")
        return

    log(f"Found {len(jobs)} unscored jobs in DB.")
    _run_scorer(jobs, profile, threshold, model)
    log("Score-only run complete.")


# ===============================================================
#  DEDUPLICATE FUNCTION
# ===============================================================
def dedupe_existing_db() -> None:
    """Remove duplicate jobs from the DB based on case-insensitive title and company."""
    _init_db()
    conn = _get_db()
    try:
        rows = conn.execute("SELECT rowid, job_id, title, company FROM jobs ORDER BY rowid").fetchall()
        seen = set()
        to_delete = []
        for row in rows:
            rowid, job_id, title, company = row
            key = (str(title).lower().strip(), str(company).lower().strip())
            if key in seen:
                to_delete.append(rowid)
            else:
                seen.add(key)
        
        if to_delete:
            log(f"Found {len(to_delete)} duplicate jobs in DB. Deleting...")
            for rowid in to_delete:
                conn.execute("DELETE FROM jobs WHERE rowid = ?", (rowid,))
            conn.commit()
            log(f"Successfully deleted {len(to_delete)} duplicate jobs.")
        else:
            log("No duplicates found in DB.")
    finally:
        conn.close()


# ===============================================================
#  MAIN RUN FUNCTION
# ===============================================================
def run(query: str | None = None, model: str = "qwen2.5:7b", **kwargs) -> None:
    """Core scout logic: scrape new jobs then score them."""

    # ── 0. Validate Ollama is running (needed for scoring) ───
    check_ollama()

    # ── 1. Init DB and load profile ──────────────────────────
    _init_db()
    profile = _load_profile()
    threshold = read_score_threshold(profile)

    # ── 2. Build search queries ──────────────────────────────
    queries = [query] if query else _read_queries_from_profile(profile)
    if not queries:
        queries = ["AI Engineer entry level"]

    log(f"Starting scout with queries: {queries}")

    # ── 3. Scrape & save new jobs ────────────────────────────
    new_jobs_found = []
    
    blocked_companies = [c.lower() for c in _load_blocked_companies(profile)]
    blocked_keywords = [k.lower() for k in _load_blocked_keywords(profile)]
    spam_count = 0

    for q in queries:
        raw_jobs = _fetch_jobs(q)
        for raw in raw_jobs:
            fmt_job = _format_jobspy_job(raw)
            if not fmt_job["job_id"]:
                continue

            company_lower = fmt_job.get("company", "").lower()
            if company_lower in blocked_companies or any(k in company_lower for k in blocked_keywords):
                spam_count += 1
                continue

            if not _job_exists(fmt_job["job_id"], fmt_job.get("title", ""), fmt_job.get("company", "")):
                _save_job(fmt_job)
                new_jobs_found.append(fmt_job)

    if spam_count > 0:
        log(f"Filtered {spam_count} spam/scam listings")

    log(f"Found {len(new_jobs_found)} new unique jobs overall.")

    # ── 4. Score new jobs ────────────────────────────────────
    if not new_jobs_found:
        log("No new jobs to score.")
        return

    _run_scorer(new_jobs_found, profile, threshold, model)
    log("Scout complete.")


# ===============================================================
#  CLI ENTRY POINT
# ===============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find fresh job listings and score them.")
    parser.add_argument("--query", type=str, help="Specific job search query (e.g. 'AI Engineer intern')")
    parser.add_argument("--model", type=str, default="qwen2.5:7b", help="Ollama model to use for scoring")
    parser.add_argument(
        "--score-only",
        action="store_true",
        help="Score existing NULL-score jobs in DB without re-scraping",
    )
    parser.add_argument(
        "--dedupe",
        action="store_true",
        help="Remove duplicate jobs from DB based on title and company",
    )

    args = parser.parse_args()

    if args.dedupe:
        dedupe_existing_db()
    elif args.score_only:
        score_existing(model=args.model)
    else:
        run(query=args.query, model=args.model)
