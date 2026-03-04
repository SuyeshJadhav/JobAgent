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

## Database Format (CSV)

```csv
job_id, title, company, location, apply_link, description, score, reason, found_at, applied_at, status, resume_path, cover_letter_path, notes, last_updated
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

## API Integration
Endpoint: `GET /api/tracker/stats` or `backend/services/csv_tracker.py`

## Rules
- Every pipeline action must update the tracker
- Never delete rows — only update status
- Always record `last_updated` timestamp on any change
- Rejected/failed jobs stay in DB for learning
