# API Reference

Base URL: `http://127.0.0.1:8000`

## Root / App

### GET /

- Source: `backend/main.py`
- Response:

```json
{ "status": "ok", "message": "JobAgent Backend API is running." }
```

## Apply Router (`/api/apply`)

Source: `backend/routers/apply.py`

### GET /api/apply/{job_id}/payload

Returns extension payload for tracked job.

Path params:

- `job_id: string`

Responses:

- `200`:

```json
{
  "job_id": "...",
  "company": "...",
  "resume_path": "...",
  "cover_letter_path": "..."
}
```

- `404`: `{ "detail": "Job not found" }`

## Profile Router (`/api/profile`)

Source: `backend/routers/profile.py`

### GET /api/profile

Returns all markdown files under `profile/` as `{filename: content}` map.

### POST /api/profile/fill

Request body (`FillRequest`):

```json
{
  "fields": ["First name", "Why this role?"],
  "job_url": "",
  "company": "",
  "job_description": ""
}
```

Response:

- key-value answer dictionary,
- includes `resume_automation` when `job_description` is provided.

### POST /api/profile/application_complete

Request body (`CompleteRequest`):

```json
{
  "job_url": "https://...",
  "company": "Example",
  "is_generated": false,
  "generated_resume_path": ""
}
```

Response:

```json
{ "status": "success", "message": "Job tracked and cleanup complete" }
```

### POST /api/profile/{filename}

Updates a markdown file in `profile/`.

Request body (`ProfileUpdate`):

```json
{ "content": "..." }
```

Validation:

- rejects empty content (`400`),
- only `.md` filename allowed (`400`).

Response:

```json
{ "status": "success", "filename": "skills.md" }
```

## Scout Router (`/api/scout`)

Source: `backend/routers/scout.py`

### POST /api/scout/run

Triggers fetch + dedupe + insert + background processing.

Response shape:

```json
{
  "total_discovered": 0,
  "simplify_count": 0,
  "ats_count": 0,
  "serper_count": 0,
  "unique_count": 0,
  "input_job_types": [],
  "recognized_job_types": [],
  "ignored_job_types": [],
  "message": "Triggered knockout pipeline for X jobs."
}
```

### GET /api/scout/jobs?status={status}

Returns DB jobs (optionally filtered by status).

### GET /api/scout/jobs/{job_id}

Returns merged job details (DB row + local `job_details.json` description when available).

### GET /api/scout/check_url?url={url}

Response when matched:

```json
{ "tracked": true, "job": { "...": "..." } }
```

Otherwise:

```json
{ "tracked": false }
```

### POST /api/scout/jobs/{job_id}/rescore

Re-runs organic scoring path for an existing job.

- `404` if job not found.

### POST /api/scout/organic

Request body (`OrganicTrackRequest`):

```json
{
  "url": "https://...",
  "title": "",
  "company": "",
  "page_text": ""
}
```

Returns `track_organic_job` result (status, score, reason, job_status, etc.).

## Settings Router (`/api/settings`)

Source: `backend/routers/settings.py`

### GET /api/settings

Returns full JSON from `backend/config/settings.json` (or `{}` if missing).

### POST /api/settings

Request body: arbitrary JSON object (saved as settings file).

Response:

```json
{ "saved": true, "llm_ok": true }
```

`llm_ok` comes from `test_connection()`.

## Sniper Router (`/api/sniper`)

Source: `backend/routers/sniper.py`

### POST /api/sniper/answer

Request body (`AnswerRequest`):

```json
{
  "url": "https://...",
  "job_id": "optional",
  "questions": ["Question 1", "Question 2"]
}
```

Response:

- dictionary keyed by question text,
- may include `resume_base64` and `resume_filename` for matched/high-score jobs.

### POST /api/sniper/complete

Request body (`CompleteRequest`):

```json
{ "url": "https://...", "job_id": "optional" }
```

Response:

```json
{
  "status": "applied_and_cleaned",
  "job_id": "...",
  "shredded": ["outputs/applications/..."],
  "message": "Application recorded. N artifact dir(s) destroyed."
}
```

- `404` when job cannot be matched.

## Tailor Router (`/api/tailor`)

Source: `backend/routers/tailor.py`

### POST /api/tailor/generate

JIT tailored resume generation.

Request body (`GenerateRequest`):

```json
{ "job_id": "optional", "url": "optional" }
```

Response:

```json
{
  "job_id": "...",
  "resume_base64": "...",
  "filename": "Suyesh_Jadhav.pdf"
}
```

Error cases:

- `404` job/details missing,
- `400` insufficient JD after scrape,
- `500` tailor/PDF failure.

### POST /api/tailor/generate_cover_letter

Request body: same `GenerateRequest`.

Response:

```json
{
  "job_id": "...",
  "cover_letter_base64": "...",
  "filename": "cover_letter.md"
}
```

### POST /api/tailor/single/{job_id}

Runs full pipeline for one shortlisted job.

Checks:

- job exists,
- details file exists,
- score >= threshold,
- status is `shortlisted`.

Response:

```json
{
  "job_id": "...",
  "status": "tailored",
  "resume_path": "...",
  "cover_letter_path": "...",
  "output_folder": "..."
}
```

### GET /api/tailor/outputs

Returns generated output folders:

```json
{ "folders": ["..."] }
```

### POST /api/tailor/run_pending

Queues background tailoring for all shortlisted jobs.

Response:

```json
{
  "message": "Triggered parallel tailoring for N shortlisted jobs (concurrency=2).",
  "count": N
}
```

## Tracker Router (`/api/tracker`)

Source: `backend/routers/tracker.py`

### GET /api/tracker/stats

Returns status counts + `total`.

### GET /api/tracker/jobs?status={status}

Returns jobs from SQLite.

### PATCH /api/tracker/{job_id}/status

Request body: arbitrary dict forwarded to `update_job(**body)`.

Response:

```json
{ "updated": true }
```

- `404` if job missing.

### DELETE /api/tracker/rejected

Deletes all rejected jobs.

Response:

```json
{ "deleted": true, "count": 0 }
```

### DELETE /api/tracker/{job_id}

Deletes one job.

Response:

```json
{ "deleted": true, "job_id": "..." }
```

- `404` if not found.

## Tracking Router (legacy, no prefix)

Source: `backend/routers/tracking.py`

### POST /track_job

Request body (`TrackJobPayload`):

```json
{ "title": "...", "company": "...", "url": "..." }
```

Current behavior:

```json
{ "status": "success", "message": "Google Sheets sync not available" }
```

### POST /sync_github_jobs?job_types=internship,newgrad

Current behavior after fetching jobs:

```json
{
  "status": "success",
  "message": "Google Sheets sync not available",
  "total_fetched": 0,
  "added": 0,
  "skipped": 0
}
```

May return `400` when `job_types` parses to empty list.
