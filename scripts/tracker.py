"""
Tracker — view, filter, update, and export job application data.

Usage:
    python scripts/tracker.py --show
    python scripts/tracker.py --show-all
    python scripts/tracker.py --status applied
    python scripts/tracker.py --stats
    python scripts/tracker.py --update <job_id> --set-status rejected
    python scripts/tracker.py --export
    python scripts/tracker.py --sync

Pipeline import:
    from scripts.tracker import run
    run(show=True)
"""

import argparse
import csv
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from utils import log

# ── Paths ────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "scout_jobs.db"
EXPORT_PATH = ROOT_DIR / "jobs_export.csv"

# ── Status lifecycle (ordered) ───────────────────────────────
# Main forward path + terminal/branch statuses
STATUS_ORDER = [
    "found",
    "shortlisted",
    "resume_ready",
    "cover_ready",
    "applied",
    "interviewing",
    "rejected",
    "offer",
]
# These can be set from any state (side branches)
SIDE_STATUSES = {"skipped", "failed", "manual_needed"}


# ── Database ─────────────────────────────────────────────────
def _get_db():
    """Return a sqlite3 connection with Row factory."""
    if not DB_PATH.exists():
        log(f"Database not found at {DB_PATH}. No data to show.")
        return None
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_jobs(
    status_filter: str | None = None,
    include_skipped: bool = False,
) -> list[dict]:
    """Fetch jobs, optionally filtered by status."""
    conn = _get_db()
    if not conn:
        return []
    try:
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY last_updated DESC",
                (status_filter,),
            ).fetchall()
        elif include_skipped:
            rows = conn.execute("SELECT * FROM jobs ORDER BY last_updated DESC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs WHERE status != 'skipped' ORDER BY last_updated DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Lifecycle enforcement ────────────────────────────────────
def _can_transition(current: str, target: str) -> bool:
    """
    Check if transitioning from current → target is valid.
    Forward-only along the lifecycle; side statuses allowed from anywhere.
    """
    if target in SIDE_STATUSES:
        return True

    if current in SIDE_STATUSES:
        # Can't move back from a terminal side status into the main path
        # except manual_needed → can retry
        if current == "manual_needed":
            return target in STATUS_ORDER
        return False

    try:
        cur_idx = STATUS_ORDER.index(current)
        tgt_idx = STATUS_ORDER.index(target)
        return tgt_idx >= cur_idx
    except ValueError:
        # Unknown status — allow it
        return True


# ── Table printer ────────────────────────────────────────────
def _print_table(jobs: list[dict]) -> None:
    """Print jobs as a clean aligned table."""
    if not jobs:
        print("\n  No jobs found.\n")
        return

    # Column definitions: (header, key, max_width)
    columns = [
        ("#", None, 4),
        ("Title", "title", 30),
        ("Company", "company", 20),
        ("Score", "score", 5),
        ("Status", "status", 15),
        ("Applied At", "applied_at", 20),
    ]

    # Build header
    header_parts = []
    for hdr, _, width in columns:
        header_parts.append(hdr.ljust(width))
    header = "  ".join(header_parts)

    print()
    print(header)
    print("-" * len(header))

    for i, job in enumerate(jobs, 1):
        row_parts = []
        for hdr, key, width in columns:
            if key is None:
                val = str(i)
            else:
                val = str(job.get(key) or "-")
            # Truncate if too long
            if len(val) > width:
                val = val[: width - 1] + "..."
            row_parts.append(val.ljust(width))
        print("  ".join(row_parts))

    print("-" * len(header))
    print(f"  Total: {len(jobs)} job(s)\n")


# ── Stats ────────────────────────────────────────────────────
def _print_stats() -> None:
    """Print summary counts grouped by status."""
    conn = _get_db()
    if not conn:
        return
    try:
        rows = conn.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status ORDER BY cnt DESC").fetchall()
    finally:
        conn.close()

    if not rows:
        print("\n  No jobs in database.\n")
        return

    total = sum(r["cnt"] for r in rows)

    print()
    print("  Status              Count")
    print("  " + "-" * 30)
    for r in rows:
        status = r["status"] or "unknown"
        cnt = r["cnt"]
        bar = "#" * min(cnt, 40)
        print(f"  {status:<20} {cnt:>4}  {bar}")
    print("  " + "-" * 30)
    print(f"  {'TOTAL':<20} {total:>4}")
    print()


# ── Update status ────────────────────────────────────────────
def _update_status(job_id: str, new_status: str) -> bool:
    """
    Update a job's status with lifecycle enforcement.
    Returns True on success, False on failure.
    """
    conn = _get_db()
    if not conn:
        return False
    try:
        row = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()

        if not row:
            log(f"ERROR: Job {job_id} not found in DB.")
            return False

        current = row["status"] or "found"

        if not _can_transition(current, new_status):
            log(f"ERROR: Cannot transition {current} → {new_status}. Lifecycle violation (forward-only).")
            return False

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE jobs SET status = ?, last_updated = ? WHERE job_id = ?",
            (new_status, now, job_id),
        )
        conn.commit()
        log(f"Updated: job_id={job_id} → {current} → {new_status}")
        return True
    finally:
        conn.close()


# ── CSV export ───────────────────────────────────────────────
def _export_csv() -> str | None:
    """Dump all rows to jobs_export.csv. Returns path on success."""
    conn = _get_db()
    if not conn:
        return None
    try:
        rows = conn.execute("SELECT * FROM jobs ORDER BY last_updated DESC").fetchall()
        if not rows:
            log("No data to export.")
            return None

        headers = rows[0].keys()
        with open(EXPORT_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for r in rows:
                writer.writerow(dict(r))

        log(f"Exported {len(rows)} rows → {EXPORT_PATH}")
        return str(EXPORT_PATH)
    finally:
        conn.close()


# ── Google Sheets sync (optional) ────────────────────────────
def _sync_to_sheets() -> bool:
    """
    Push all rows to Google Sheets if GOOGLE_SHEETS_ID is set.
    Skips silently if not configured — never crashes.
    """
    sheet_id = os.environ.get("GOOGLE_SHEETS_ID")
    creds_path = os.environ.get("GOOGLE_CREDS_PATH")

    if not sheet_id:
        log("GOOGLE_SHEETS_ID not set — skipping Sheets sync.")
        return False

    if not creds_path or not Path(creds_path).exists():
        log("GOOGLE_CREDS_PATH not set or file missing — skipping Sheets sync.")
        return False

    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        log(
            "google-api-python-client not installed — skipping Sheets sync.\n"
            "  Install with: pip install google-api-python-client google-auth"
        )
        return False

    conn = _get_db()
    if not conn:
        return False
    try:
        rows = conn.execute("SELECT * FROM jobs ORDER BY last_updated DESC").fetchall()
        if not rows:
            log("No data to sync.")
            return False

        headers = list(rows[0].keys())
        values = [headers] + [[str(r[h] or "") for h in headers] for r in rows]

        creds = Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        service = build("sheets", "v4", credentials=creds)
        sheet = service.spreadsheets()

        sheet.values().update(
            spreadsheetId=sheet_id,
            range="Sheet1!A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()

        log(f"Synced {len(rows)} rows to Google Sheets ({sheet_id})")
        return True
    except Exception as e:
        log(f"Sheets sync error: {e}")
        return False
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
#  MAIN RUN FUNCTION
# ═══════════════════════════════════════════════════════════════
def run(
    job_id: str | None = None,
    show: bool = False,
    show_all: bool = False,
    status: str | None = None,
    stats: bool = False,
    update: str | None = None,
    set_status: str | None = None,
    export: bool = False,
    sync: bool = False,
    **kwargs,
) -> None:
    """
    Core tracker logic. Works both standalone and when imported.
    """

    # Stats
    if stats:
        _print_stats()
        return

    # Show (filtered)
    if show or show_all or status:
        jobs = _fetch_jobs(
            status_filter=status,
            include_skipped=show_all,
        )
        _print_table(jobs)
        return

    # Update status
    if update and set_status:
        _update_status(update, set_status)
        return
    elif update and not set_status:
        log("ERROR: --update requires --set-status")
        return

    # Export
    if export:
        _export_csv()
        return

    # Sync
    if sync:
        _sync_to_sheets()
        return

    # Default: show non-skipped
    log("No action specified. Showing all non-skipped jobs (use --help for options).")
    jobs = _fetch_jobs(include_skipped=False)
    _print_table(jobs)


# ═══════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track, view, and manage job application statuses.")
    parser.add_argument("--show", action="store_true", help="Show all non-skipped applications")
    parser.add_argument("--show-all", action="store_true", help="Show all applications including skipped")
    parser.add_argument("--status", type=str, help="Filter by status (e.g. applied, shortlisted)")
    parser.add_argument("--stats", action="store_true", help="Show summary counts by status")
    parser.add_argument("--update", type=str, metavar="JOB_ID", help="Job ID to update (use with --set-status)")
    parser.add_argument("--set-status", type=str, metavar="STATUS", help="New status to set (use with --update)")
    parser.add_argument("--export", action="store_true", help="Export all rows to jobs_export.csv")
    parser.add_argument("--sync", action="store_true", help="Sync to Google Sheets (requires GOOGLE_SHEETS_ID env var)")

    args = parser.parse_args()

    run(
        show=args.show,
        show_all=args.show_all,
        status=args.status,
        stats=args.stats,
        update=args.update,
        set_status=args.set_status,
        export=args.export,
        sync=args.sync,
    )
