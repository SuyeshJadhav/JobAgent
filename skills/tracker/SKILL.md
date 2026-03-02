---
name: tracker
description: >
  Logs and tracks all job applications, statuses, and outcomes. Use when user asks to see
  applications, update a status, check progress, or sync to Google Sheets.
  Always the last step in the pipeline. Every action in the pipeline writes to the tracker.
---

# Tracker Skill

Single source of truth for all applications. Every job that touches the pipeline
gets logged here — from found to applied to offer.

---

## Database Schema (SQLite)

```sql
CREATE TABLE jobs (
  job_id        TEXT PRIMARY KEY,
  title         TEXT,
  company       TEXT,
  location      TEXT,
  apply_link    TEXT,
  description   TEXT,
  score         INTEGER,
  reason        TEXT,
  found_at      TEXT,
  applied_at    TEXT,
  status        TEXT,        -- see statuses below
  resume_path   TEXT,        -- path to tailored resume
  cover_letter_path TEXT,
  notes         TEXT,
  last_updated  TEXT
)
```

## Job Statuses (lifecycle)

```
found → shortlisted → resume_ready → cover_ready → applied → [interviewing / rejected / offer]
                ↘ skipped (score < 6)
                              ↘ manual_needed (CAPTCHA / unknown form)
                                            ↘ failed (apply error)
```

## Commands the Agent Understands

| User says | Action |
|---|---|
| "show my applications" | Print all rows with status ≠ skipped |
| "what's shortlisted" | Filter status = shortlisted |
| "mark X as rejected" | Update status for that job |
| "sync to sheets" | Push all rows to Google Sheets |
| "how many applied today" | Count applied_at = today |

## Google Sheets Sync (optional)
- Uses Google Sheets API
- Sheet columns mirror DB schema
- Sync runs after each apply batch
- Env var: `GOOGLE_SHEETS_ID`, `GOOGLE_CREDS_PATH`

## Script
Run: `scripts/tracker.py --show` or `--sync`

## Rules
- Every pipeline action must update the tracker
- Never delete rows — only update status
- Always record `last_updated` timestamp on any change
- Rejected/failed jobs stay in DB for learning
