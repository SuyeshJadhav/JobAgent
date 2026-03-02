"""
Pipeline -- orchestrator that chains all job application modules together.

Usage:
    python scripts/pipeline.py --full                    run everything
    python scripts/pipeline.py --full --dry-run          full pipeline, no apply clicks
    python scripts/pipeline.py --from tailor             start from tailor onwards
    python scripts/pipeline.py --job_id <id>             tailor > cover > apply for one job
    python scripts/pipeline.py --job_id <id> --no-compile skip PDF compilation

Pipeline order (always):
    scout > tailor > cover > apply > track
"""

import argparse
import sqlite3
import sys
from pathlib import Path

from utils import log

# ── Paths ────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
DB_PATH = ROOT_DIR / "scout_jobs.db"

# ── Add scripts dir to path for imports ──────────────────────
sys.path.insert(0, str(SCRIPTS_DIR))

from resume_tailor import run as tailor_run  # noqa: E402
from cover_letter import run as cover_run  # noqa: E402
from auto_apply import run as apply_run  # noqa: E402
from tracker import run as tracker_run  # noqa: E402

# Scout is optional -- may not be built yet
try:
    from scout_agent import run as scout_run
except ImportError:
    scout_run = None

# ── Module ordering ──────────────────────────────────────────
MODULE_ORDER = ["scout", "tailor", "cover", "apply", "track"]


def _banner(text: str) -> None:
    print()
    print("=" * 60)
    print(f"  {text}")
    print("=" * 60)


# ── Database queries ─────────────────────────────────────────
def _get_db():
    """Return a sqlite3 connection, or None if DB doesn't exist."""
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _count_by_status() -> dict[str, int]:
    """Return {status: count} for all jobs."""
    conn = _get_db()
    if not conn:
        return {}
    try:
        rows = conn.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["cnt"] for r in rows}
    finally:
        conn.close()


def _get_jobs_by_status(status: str) -> list[dict]:
    """Fetch all jobs with a given status."""
    conn = _get_db()
    if not conn:
        return []
    try:
        rows = conn.execute("SELECT * FROM jobs WHERE status = ?", (status,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Pipeline stages ──────────────────────────────────────────


def _run_scout() -> int:
    """Run scout agent. Returns number of jobs found/shortlisted."""
    _banner("STAGE 1: SCOUT -- Finding jobs")

    if scout_run is None:
        log("scout_agent.py not found -- skipping scout stage.")
        log("(Build scout_agent.py or use --from tailor to skip)")
        return 0

    try:
        scout_run()
    except Exception as e:
        log(f"Scout error: {e}")
        return 0

    counts = _count_by_status()
    shortlisted = counts.get("shortlisted", 0)
    found = counts.get("found", 0)
    log(f"Scout complete. Found: {found}, Shortlisted: {shortlisted}")
    return shortlisted


def _run_tailor(
    job_ids: list[str] | None = None,
    no_compile: bool = False,
) -> int:
    """Run resume tailor. Returns number successfully tailored."""
    _banner("STAGE 2: RESUME TAILOR -- Rewriting bullets per JD")

    # If specific job_ids provided, use those; otherwise query DB
    if not job_ids:
        jobs = _get_jobs_by_status("shortlisted")
        if not jobs:
            log("No shortlisted jobs to tailor. Skipping.")
            return 0
        job_ids = [j["job_id"] for j in jobs]

    log(f"Tailoring resumes for {len(job_ids)} job(s)...")

    success = 0
    for i, jid in enumerate(job_ids, 1):
        log(f"  [{i}/{len(job_ids)}] Tailoring job_id={jid}")
        try:
            result = tailor_run(job_id=jid, no_compile=no_compile)
            if result:
                success += 1
                log(f"  [OK] Done: {result}")
            else:
                log(f"  [FAIL] Skipped or failed: {jid}")
        except Exception as e:
            log(f"  [FAIL] Error: {e}")

    log(f"Tailor complete. Succeeded: {success}/{len(job_ids)}")
    return success


def _run_cover(job_ids: list[str] | None = None) -> int:
    """Run cover letter generator. Returns number generated."""
    _banner("STAGE 3: COVER LETTER -- Generating per JD")

    if not job_ids:
        jobs = _get_jobs_by_status("resume_ready")
        if not jobs:
            log("No resume_ready jobs to write cover letters for. Skipping.")
            return 0
        job_ids = [j["job_id"] for j in jobs]

    log(f"Generating cover letters for {len(job_ids)} job(s)...")

    success = 0
    for i, jid in enumerate(job_ids, 1):
        log(f"  [{i}/{len(job_ids)}] Cover letter for job_id={jid}")
        try:
            result = cover_run(job_id=jid)
            if result:
                success += 1
                log(f"  [OK] Done: {result}")
            else:
                log(f"  [FAIL] Skipped or failed: {jid}")
        except Exception as e:
            log(f"  [FAIL] Error: {e}")

    log(f"Cover letter complete. Succeeded: {success}/{len(job_ids)}")
    return success


def _run_apply(
    job_ids: list[str] | None = None,
    dry_run: bool = False,
) -> int:
    """Run auto-apply. Returns number applied."""
    _banner("STAGE 4: AUTO-APPLY -- Submitting applications")

    if dry_run:
        log("DRY RUN mode -- no applications will be submitted")

    if job_ids and len(job_ids) == 1:
        # Single job mode
        results = apply_run(job_id=job_ids[0], dry_run=dry_run)
    else:
        # Batch mode -- apply to all cover_ready jobs
        results = apply_run(batch=True, dry_run=dry_run)

    applied = sum(1 for r in results if r.get("status") == "applied")
    log(f"Apply complete. Applied: {applied}/{len(results)}")
    return applied


def _run_track() -> None:
    """Show tracker summary."""
    _banner("STAGE 5: TRACKER -- Summary")
    tracker_run(stats=True)


# ── Summary printer ─────────────────────────────────────────
def _print_summary(counters: dict) -> None:
    """Print final pipeline summary."""
    print()
    print("+" + "-" * 40 + "+")
    print("|       PIPELINE RUN SUMMARY            |")
    print("+" + "-" * 40 + "+")
    print(f"|  Jobs found:         {counters.get('found', '-'):>14}  |")
    print(f"|  Jobs shortlisted:   {counters.get('shortlisted', '-'):>14}  |")
    print(f"|  Resumes tailored:   {counters.get('tailored', '-'):>14}  |")
    print(f"|  Cover letters:      {counters.get('cover', '-'):>14}  |")
    print(f"|  Applied:            {counters.get('applied', '-'):>14}  |")
    print(f"|  Failed/skipped:     {counters.get('failed', '-'):>14}  |")
    print("+" + "-" * 40 + "+")
    print()


# ═══════════════════════════════════════════════════════════════
#  MAIN RUN FUNCTION
# ═══════════════════════════════════════════════════════════════
def run(
    job_id: str | None = None,
    full: bool = False,
    from_module: str | None = None,
    dry_run: bool = False,
    no_compile: bool = False,
    **kwargs,
) -> dict:
    """
    Core pipeline orchestrator.
    Returns a summary dict with counts per stage.
    """

    counters: dict[str, int | str] = {
        "found": "-",
        "shortlisted": "-",
        "tailored": "-",
        "cover": "-",
        "applied": "-",
        "failed": "-",
    }

    # ── Single job mode ──────────────────────────────────────
    if job_id:
        _banner(f"PIPELINE — Single job: {job_id}")
        log("Running: tailor > cover > apply for one job")

        t = _run_tailor(job_ids=[job_id], no_compile=no_compile)
        counters["tailored"] = t

        if t > 0:
            c = _run_cover(job_ids=[job_id])
            counters["cover"] = c
            if c > 0:
                a = _run_apply(job_ids=[job_id], dry_run=dry_run)
                counters["applied"] = a
            else:
                log("Cover letter failed -- skipping apply.")
        else:
            log("Resume tailor failed -- skipping cover + apply.")

        _run_track()
        _print_summary(counters)
        return counters

    # ── Determine start module ───────────────────────────────
    if from_module:
        if from_module not in MODULE_ORDER:
            log(f"ERROR: Unknown module '{from_module}'. Valid: {', '.join(MODULE_ORDER)}")
            return counters
        start_idx = MODULE_ORDER.index(from_module)
    elif full:
        start_idx = 0
    else:
        log("ERROR: Provide --full, --from <module>, or --job_id <id>")
        return counters

    modules_to_run = MODULE_ORDER[start_idx:]
    _banner(f"PIPELINE -- Running: {' > '.join(modules_to_run)}")

    # ── Execute modules in order ─────────────────────────────

    # SCOUT
    if "scout" in modules_to_run:
        _run_scout()
        # After scout, count what we have
        counts = _count_by_status()
        counters["found"] = counts.get("found", 0) + counts.get("shortlisted", 0)
        counters["shortlisted"] = counts.get("shortlisted", 0)

    # TAILOR
    if "tailor" in modules_to_run:
        t = _run_tailor(no_compile=no_compile)
        counters["tailored"] = t

    # COVER
    if "cover" in modules_to_run:
        c = _run_cover()
        counters["cover"] = c

    # APPLY (always requires user confirmation -- never auto-submit)
    if "apply" in modules_to_run:
        a = _run_apply(dry_run=dry_run)
        counters["applied"] = a

    # TRACK
    if "track" in modules_to_run:
        _run_track()

    # Final failed/skipped count from DB
    counts = _count_by_status()
    failed = counts.get("failed", 0) + counts.get("skipped", 0) + counts.get("manual_needed", 0)
    counters["failed"] = failed

    _print_summary(counters)
    return counters


# ═══════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pipeline orchestrator -- chains all job application modules together.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/pipeline.py --full                  Run entire pipeline\n"
            "  python scripts/pipeline.py --full --dry-run        Full pipeline, no apply clicks\n"
            "  python scripts/pipeline.py --from tailor           Start from tailor onwards\n"
            "  python scripts/pipeline.py --job_id abc123         tailor>cover>apply for one job\n"
            "  python scripts/pipeline.py --from cover --dry-run  Cover + apply (preview)\n"
        ),
    )
    parser.add_argument("--full", action="store_true", help="Run entire pipeline start to finish")
    parser.add_argument(
        "--from",
        dest="from_module",
        type=str,
        metavar="MODULE",
        choices=MODULE_ORDER,
        help=f"Start from a specific module onwards. Values: {', '.join(MODULE_ORDER)}",
    )
    parser.add_argument("--job_id", type=str, help="Run tailor > cover > apply for a single job")
    parser.add_argument("--dry-run", action="store_true", help="Pass dry-run to auto_apply -- no actual clicks")
    parser.add_argument("--no-compile", action="store_true", help="Pass no-compile to resume_tailor -- skip PDF")

    args = parser.parse_args()

    if not args.full and not args.from_module and not args.job_id:
        parser.print_help()
        sys.exit(1)

    run(
        job_id=args.job_id,
        full=args.full,
        from_module=args.from_module,
        dry_run=args.dry_run,
        no_compile=args.no_compile,
    )
