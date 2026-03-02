"""
Auto Apply — Playwright-based job application automation.

Usage:
    python scripts/auto_apply.py --job_id <id>
    python scripts/auto_apply.py --batch          ← apply to all cover_ready jobs
    python scripts/auto_apply.py --batch --dry-run ← preview only, no clicks

Pipeline import:
    from scripts.auto_apply import run
    run(job_id="abc123")
"""

import argparse
import json
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from utils import log

# ── Paths ────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "scout_jobs.db"
CONFIG_DIR = ROOT_DIR / "config"
SCREENSHOTS_DIR = ROOT_DIR / "outputs" / "screenshots"

LINKEDIN_COOKIES = CONFIG_DIR / "linkedin_cookies.json"
INDEED_COOKIES = CONFIG_DIR / "indeed_cookies.json"

# ── Constants ────────────────────────────────────────────────
MAX_APPLICATIONS_PER_RUN = 10
RATE_LIMIT_MIN = 30  # seconds
RATE_LIMIT_MAX = 60  # seconds


# ── Database ─────────────────────────────────────────────────
def _get_db():
    """Return a sqlite3 connection with Row factory."""
    if not DB_PATH.exists():
        sys.exit(f"ERROR: Database not found at {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_job_from_db(job_id: str) -> dict | None:
    """Query a single job by job_id (TEXT primary key)."""
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_cover_ready_jobs() -> list[dict]:
    """Fetch all jobs with status = 'cover_ready'."""
    conn = _get_db()
    try:
        rows = conn.execute("SELECT * FROM jobs WHERE status = 'cover_ready'").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_job_status(
    job_id: str,
    status: str,
    notes: str | None = None,
    applied_at: str | None = None,
) -> None:
    """Update a job's status, notes, and timestamps in the DB."""
    conn = _get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        if applied_at:
            conn.execute(
                """UPDATE jobs
                   SET status = ?, notes = ?, applied_at = ?, last_updated = ?
                   WHERE job_id = ?""",
                (status, notes, applied_at, now, job_id),
            )
        else:
            conn.execute(
                """UPDATE jobs
                   SET status = ?, notes = ?, last_updated = ?
                   WHERE job_id = ?""",
                (status, notes, now, job_id),
            )
        conn.commit()
        log(f"DB: job_id={job_id} → status={status}")
    finally:
        conn.close()


# ── Portal detection ─────────────────────────────────────────
def _detect_portal(apply_link: str) -> str:
    """Detect which portal a link belongs to."""
    link = apply_link.lower()
    if "linkedin.com" in link:
        return "linkedin"
    elif "indeed.com" in link:
        return "indeed"
    elif "handshake" in link:
        return "handshake"
    else:
        return "other"


# ── Cookie loading ───────────────────────────────────────────
def _load_cookies(page, portal: str) -> bool:
    """Load saved session cookies for a portal. Returns True if loaded."""

    cookie_path = {
        "linkedin": LINKEDIN_COOKIES,
        "indeed": INDEED_COOKIES,
    }.get(portal)

    if not cookie_path or not cookie_path.exists():
        log(f"  No saved cookies for {portal}")
        return False

    try:
        cookies = json.loads(cookie_path.read_text(encoding="utf-8"))
        page.context.add_cookies(cookies)
        log(f"  Loaded cookies for {portal}")
        return True
    except Exception as e:
        log(f"  Failed to load cookies for {portal}: {e}")
        return False


# ── CAPTCHA detection ────────────────────────────────────────
def _check_captcha(page) -> bool:
    """Check if the current page has a CAPTCHA challenge."""
    captcha_selectors = [
        "iframe[src*='captcha']",
        "iframe[src*='recaptcha']",
        "#captcha",
        ".captcha",
        "[data-captcha]",
        "iframe[title*='challenge']",
    ]
    for sel in captcha_selectors:
        if page.query_selector(sel):
            return True

    # Check page text for captcha keywords
    body_text = page.inner_text("body").lower()
    if any(kw in body_text for kw in ["verify you are human", "captcha", "security challenge"]):
        return True

    return False


# ── Screenshot helper ────────────────────────────────────────
def _take_screenshot(page, job_id: str, label: str) -> str | None:
    """Save a screenshot and return the path."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOTS_DIR / f"{job_id}_{label}_{ts}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
        log(f"  Screenshot: {path.name}")
        return str(path)
    except Exception as e:
        log(f"  Screenshot failed: {e}")
        return None


# ── LinkedIn Easy Apply ──────────────────────────────────────
def _apply_linkedin(page, job: dict) -> str:
    """
    Attempt LinkedIn Easy Apply.
    Returns: 'applied', 'manual_needed', or 'failed'
    """
    apply_link = job["apply_link"]
    resume_path = job.get("resume_path", "")

    try:
        page.goto(apply_link, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        if _check_captcha(page):
            _take_screenshot(page, job["job_id"], "captcha")
            return "manual_needed"

        # Look for Easy Apply button
        easy_apply_btn = page.query_selector('button:has-text("Easy Apply"), button:has-text("Apply")')
        if not easy_apply_btn:
            _take_screenshot(page, job["job_id"], "no_apply_button")
            log("  No Easy Apply button found")
            return "manual_needed"

        easy_apply_btn.click()
        page.wait_for_timeout(2000)

        # Upload resume if file input exists
        if resume_path and Path(resume_path).exists():
            file_input = page.query_selector('input[type="file"]')
            if file_input:
                file_input.set_input_files(resume_path)
                log(f"  Uploaded resume: {Path(resume_path).name}")
                page.wait_for_timeout(1000)

        # Try to click through multi-step forms
        for step in range(5):
            next_btn = page.query_selector(
                'button:has-text("Next"), button:has-text("Continue"), button:has-text("Review")'
            )
            if next_btn:
                next_btn.click()
                page.wait_for_timeout(2000)
            else:
                break

        # Look for submit button
        submit_btn = page.query_selector('button:has-text("Submit application"), button:has-text("Submit")')
        if submit_btn:
            submit_btn.click()
            page.wait_for_timeout(3000)
            _take_screenshot(page, job["job_id"], "confirmation")
            return "applied"
        else:
            _take_screenshot(page, job["job_id"], "no_submit")
            log("  Could not find submit button")
            return "manual_needed"

    except Exception as e:
        log(f"  LinkedIn apply error: {e}")
        _take_screenshot(page, job["job_id"], "error")
        return "failed"


# ── Indeed Apply ─────────────────────────────────────────────
def _apply_indeed(page, job: dict) -> str:
    """
    Attempt Indeed Apply.
    Returns: 'applied', 'manual_needed', or 'failed'
    """
    apply_link = job["apply_link"]
    resume_path = job.get("resume_path", "")

    try:
        page.goto(apply_link, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        if _check_captcha(page):
            _take_screenshot(page, job["job_id"], "captcha")
            return "manual_needed"

        # Look for Apply button
        apply_btn = page.query_selector(
            'button:has-text("Apply now"), button:has-text("Apply on company site"), a:has-text("Apply now")'
        )
        if not apply_btn:
            _take_screenshot(page, job["job_id"], "no_apply_button")
            log("  No Apply button found")
            return "manual_needed"

        apply_btn.click()
        page.wait_for_timeout(3000)

        # Upload resume if file input available
        if resume_path and Path(resume_path).exists():
            file_input = page.query_selector('input[type="file"]')
            if file_input:
                file_input.set_input_files(resume_path)
                log(f"  Uploaded resume: {Path(resume_path).name}")
                page.wait_for_timeout(1000)

        # Paste cover letter if textarea is available
        cover_path = job.get("cover_letter_path", "")
        if cover_path and Path(cover_path).exists():
            cover_text = Path(cover_path).read_text(encoding="utf-8")
            cover_field = page.query_selector(
                'textarea[name*="cover"], textarea[id*="cover"], textarea[aria-label*="cover"]'
            )
            if cover_field:
                cover_field.fill(cover_text)
                log("  Pasted cover letter")

        # Click through steps
        for step in range(5):
            continue_btn = page.query_selector('button:has-text("Continue"), button:has-text("Next")')
            if continue_btn:
                continue_btn.click()
                page.wait_for_timeout(2000)
            else:
                break

        # Submit
        submit_btn = page.query_selector('button:has-text("Submit"), button:has-text("Apply")')
        if submit_btn:
            submit_btn.click()
            page.wait_for_timeout(3000)
            _take_screenshot(page, job["job_id"], "confirmation")
            return "applied"
        else:
            _take_screenshot(page, job["job_id"], "no_submit")
            log("  Could not find submit button")
            return "manual_needed"

    except Exception as e:
        log(f"  Indeed apply error: {e}")
        _take_screenshot(page, job["job_id"], "error")
        return "failed"


# ── Generic / unsupported portal ─────────────────────────────
def _apply_other(page, job: dict) -> str:
    """For unsupported portals, open the page and mark as manual_needed."""
    try:
        page.goto(job["apply_link"], wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        _take_screenshot(page, job["job_id"], "unsupported_portal")
    except Exception as e:
        log(f"  Navigation error: {e}")
    return "manual_needed"


# ── Confirmation prompt ──────────────────────────────────────
def _ask_confirmation(jobs: list[dict]) -> list[dict]:
    """
    Print shortlisted jobs and ask user to confirm which to apply to.
    Returns the confirmed subset.
    """
    print("\n" + "=" * 70)
    print(f"  READY TO APPLY — {len(jobs)} job(s) with status 'cover_ready'")
    print("=" * 70)

    for i, job in enumerate(jobs, 1):
        portal = _detect_portal(job.get("apply_link", ""))
        print(f"  {i}. [{portal.upper():>10}] {job.get('company', '?')} — {job.get('title', '?')}")
        print(f"     Link: {job.get('apply_link', 'N/A')}")
        print(f"     Resume: {job.get('resume_path', 'N/A')}")
        print(f"     Cover:  {job.get('cover_letter_path', 'N/A')}")
        print()

    print("=" * 70)
    answer = input("Apply to ALL of these? (y/n/comma-separated numbers): ").strip().lower()

    if answer in ("y", "yes"):
        return jobs
    elif answer in ("n", "no", ""):
        log("User declined. No applications submitted.")
        return []
    else:
        # Parse comma-separated indices
        try:
            indices = [int(x.strip()) for x in answer.split(",")]
            selected = [jobs[i - 1] for i in indices if 1 <= i <= len(jobs)]
            log(f"User selected {len(selected)} job(s)")
            return selected
        except (ValueError, IndexError):
            log("Invalid selection. No applications submitted.")
            return []


def _gather_jobs(job_id: str | None, batch: bool, max_apps: int) -> list[dict]:
    """Fetch 'cover_ready' jobs based on args, enforcing max_apps limit."""
    if job_id:
        job = get_job_from_db(job_id)
        if not job:
            log(f"ERROR: Job {job_id} not found in DB.")
            return []
        status = job.get("status", "")
        if status != "cover_ready":
            log(f"SKIP: Job status is '{status}', expected 'cover_ready'. Run cover_letter.py first.")
            return []
        jobs = [job]
    elif batch:
        jobs = get_cover_ready_jobs()
        if not jobs:
            log("No jobs with status 'cover_ready' found.")
            return []
    else:
        log("ERROR: Provide --job_id or --batch")
        return []

    if len(jobs) > max_apps:
        log(f"Capping at {max_apps} applications (found {len(jobs)})")
        jobs = jobs[:max_apps]

    return jobs


def _format_dry_run_output(jobs: list[dict]) -> list[dict]:
    """Display jobs that would be applied to without taking action."""
    print("\n" + "=" * 70)
    print("  DRY RUN — no applications will be submitted")
    print("=" * 70)
    for i, job in enumerate(jobs, 1):
        portal = _detect_portal(job.get("apply_link", ""))
        print(f"  {i}. [{portal.upper():>10}] {job.get('company', '?')} — {job.get('title', '?')}")
        print(f"     Link:   {job.get('apply_link', 'N/A')}")
        print(f"     Resume: {job.get('resume_path', 'N/A')}")
        print(f"     Cover:  {job.get('cover_letter_path', 'N/A')}")
        print()
    print("=" * 70)
    log(f"Dry run complete. {len(jobs)} job(s) would be applied to.")
    return [{"job_id": j["job_id"], "status": "dry_run"} for j in jobs]


def _apply_single_job(page, job: dict, portal: str) -> dict:
    """Dispatch application to the correct portal handler and update DB."""
    job_id_str = job["job_id"]
    company = job.get("company", "?")
    title = job.get("title", "?")

    _load_cookies(page, portal)

    if portal == "linkedin":
        result_status = _apply_linkedin(page, job)
    elif portal == "indeed":
        result_status = _apply_indeed(page, job)
    else:
        log(f"  Unsupported portal: {portal}. Marking as manual_needed.")
        result_status = _apply_other(page, job)

    # Build notes
    notes = f"{portal} | {result_status}"
    if result_status == "manual_needed":
        notes += " | CAPTCHA or unsupported form -- needs manual action"
        log(f"  [!!] MANUAL NEEDED: {company} -- {title}")
    elif result_status == "failed":
        notes += " | automation error -- check screenshots"
        log(f"  [FAIL] FAILED: {company} -- {title}")
    elif result_status == "applied":
        log(f"  [OK] APPLIED: {company} -- {title}")

    # Update DB
    applied_at = datetime.now(timezone.utc).isoformat() if result_status == "applied" else None
    update_job_status(
        job_id=job_id_str,
        status=result_status,
        notes=notes,
        applied_at=applied_at,
    )

    return {
        "job_id": job_id_str,
        "company": company,
        "title": title,
        "portal": portal,
        "status": result_status,
        "notes": notes,
    }


def _print_results_summary(results: list[dict]) -> None:
    """Print outcome metrics for the run."""
    print("\n" + "=" * 70)
    print("  APPLICATION SUMMARY")
    print("=" * 70)
    for r in results:
        icon = {"applied": "[OK]", "manual_needed": "[!!]", "failed": "[FAIL]"}.get(r["status"], "[?]")
        print(f"  {icon} [{r['portal'].upper():>10}] {r['company']} -- {r['title']}: {r['status']}")
    print("=" * 70)

    applied_count = sum(1 for r in results if r["status"] == "applied")
    manual_count = sum(1 for r in results if r["status"] == "manual_needed")
    failed_count = sum(1 for r in results if r["status"] == "failed")
    log(f"Done! Applied: {applied_count} | Manual: {manual_count} | Failed: {failed_count}")


# ═══════════════════════════════════════════════════════════════
#  MAIN RUN FUNCTION
# ═══════════════════════════════════════════════════════════════
def run(
    job_id: str | None = None,
    batch: bool = False,
    dry_run: bool = False,
    headless: bool = False,
    max_apps: int = MAX_APPLICATIONS_PER_RUN,
    **kwargs,
) -> list[dict]:
    """
    Core auto-apply logic. Works both standalone and when imported.

    Returns a list of result dicts: [{"job_id": ..., "status": ..., "notes": ...}]
    """

    jobs = _gather_jobs(job_id, batch, max_apps)
    if not jobs:
        return []

    # ── 2. Dry-run mode ──────────────────────────────────────
    if dry_run:
        return _format_dry_run_output(jobs)

    # ── 3. Ask for user confirmation (NON-NEGOTIABLE) ────────
    confirmed = _ask_confirmation(jobs)
    if not confirmed:
        return []

    # ── 4. Launch Playwright and apply ───────────────────────
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit(
            "ERROR: playwright not installed. Run:\n  pip install playwright\n  python -m playwright install chromium"
        )

    results: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for i, job in enumerate(confirmed):
            portal = _detect_portal(job.get("apply_link", ""))
            log(f"[{i + 1}/{len(confirmed)}] Applying: {job.get('company', '?')} — {job.get('title', '?')} ({portal})")

            result_dict = _apply_single_job(page, job, portal)
            results.append(result_dict)

            # Rate limit between applications (unless it's the last one)
            if i < len(confirmed) - 1:
                delay = random.randint(RATE_LIMIT_MIN, RATE_LIMIT_MAX)
                log(f"  Waiting {delay}s before next application...")
                time.sleep(delay)

        browser.close()

    # ── 5. Print summary ─────────────────────────────────────
    _print_results_summary(results)
    return results


# ═══════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-apply to jobs using Playwright browser automation.")
    parser.add_argument("--job_id", type=str, help="Apply to a single job by job_id")
    parser.add_argument("--batch", action="store_true", help="Apply to all cover_ready jobs")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be applied — no clicks")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default: visible)")
    parser.add_argument(
        "--max-apps",
        type=int,
        default=MAX_APPLICATIONS_PER_RUN,
        help=f"Max applications per run (default: {MAX_APPLICATIONS_PER_RUN})",
    )

    args = parser.parse_args()

    if not args.job_id and not args.batch:
        parser.error("Provide either --job_id or --batch")

    run(
        job_id=args.job_id,
        batch=args.batch,
        dry_run=args.dry_run,
        headless=args.headless,
        max_apps=args.max_apps,
    )
