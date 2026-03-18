# Pipeline

## Overview

JobAgent runtime is split into three practical phases:

1. Scout (discover + scrape + score)
2. Tailor (resume and cover-letter generation)
3. Apply (manual/extension flow + lifecycle updates)

## Phase 1: Scout (exact gate order)

The gate sequence below follows `ScoutProcessor.process_jobs_bg -> _process_single` in `backend/services/scout_processor.py`.

1. Gate 1: title fast-fail
   - `contains_bad_title(job.title)`
   - if matched: set status `rejected`, score `1`, reason includes blocklist match.

2. Gate 1.5: location fast-fail
   - `is_target_location(job.location)`
   - if false: set status `rejected`, score `1`, reason includes non-US location.

3. Gate 2: scrape JD
   - `scrape_full_jd(job.apply_link)`
   - if blocked/fail: set status `rejected`, score `0`, reason set to scrape failure text.

4. Gate 3: sanitize JD
   - `trim_jd_text(jd_text)`.

5. VIP title override check
   - `is_auto_shortlist_title(job.title)`
   - if true: score forced to `10`, reason `Auto-Shortlisted (Protected Title)`.

6. Gate 4 (if not VIP): dealbreaker check
   - `contains_dealbreakers(jd_text)`
   - if matched: set status `rejected`, score `1`.

7. Gate 5 (if not VIP and no dealbreaker): score with LLM rubric
   - `score_job(job, profile)`.

8. Metadata correction pass
   - if `is_garbage_metadata(company, title)` and scorer returned extracted values, update DB `company`/`title`.

9. Final status decision
   - shortlist if `score >= threshold` (`threshold` from settings, current value `6`)
   - else reject.

10. Persist details

- `save_job_details(job)` always runs (shortlisted or rejected), enabling later manual tailoring.

## Phase 2: Tailor (exact run_tailor steps)

The sequence below follows `run_tailor` in `backend/services/resume_tailor.py`.

1. Resolve output folder with `_get_readable_job_dir(job)` and create it.
2. Persist `job_details.json` with `tailored_at` timestamp.
3. Remove legacy UUID folder if present.
4. Load references via `load_references()`.
5. Parse template markers via `parse_marker_sections(base_resume_tex)`.
6. Extract JD keywords once via `extract_jd_keywords`.
7. Generate section content via `generate_tailored_content(...)`.
8. Sanitize generated content via `_sanitize_tailored_content`.
9. Build ranked projects section via `build_ranked_projects_section(...)`.
10. Inject content into template via `inject_content_into_tex(...)`.
11. Replace projects section with ranked projects section.
12. Optional deterministic mode (when `deterministic_project_bullets` is true):
    - rewrite weak project bullets deterministically,
    - rebuild experience section deterministically from context bank.
13. Persist diagnostics in `job_details.json`.
14. Compile PDF via `_compile_latex_to_pdf(...)`.
    - initial compile
    - retry 1: trim bullets
    - retry 1.5: tighten project bullets
    - retry 2: LaTeX spacing/font compression
15. Validate artifacts via `_validate_generated_resume_artifacts(...)` and append warnings.

## Phase 3: Apply (manual + extension)

Manual/extension flow in current code:

1. Fetch apply payload for a tracked job
   - `GET /api/apply/{job_id}/payload` for resume/cover paths.

2. Generate tailored artifacts on demand
   - `POST /api/tailor/generate` for resume PDF (base64).
   - `POST /api/tailor/generate_cover_letter` for cover letter content/PDF metadata.

3. Autofill answers (extension)
   - `POST /api/sniper/answer` returns field answers and optional resume base64 attachment.

4. Mark completion
   - `POST /api/sniper/complete` sets status `applied` and shreds generated artifact directories.
   - `POST /api/profile/application_complete` sets/updates applied status and optional generated-resume cleanup.

## Status Lifecycle

Status transition logic comes from `_can_transition` in `backend/services/db_tracker.py`.

Primary ordered states:

- `found -> shortlisted -> tailored -> applied -> interviewing -> rejected -> offer`

Side-branch statuses:

- `skipped`, `failed`, `manual_needed`

Rules:

- transitions to side branches are always allowed,
- transitions from side branches are allowed,
- otherwise transitions are forward-only based on order index,
- unknown statuses default to allowed (ValueError fallback path).

## Daily Workflow

1. Run scout (`POST /api/scout/run`).
2. Review stats/jobs (`/api/tracker/stats`, `/api/scout/jobs`).
3. Focus on shortlisted jobs (`status = shortlisted`).
4. Tailor selected jobs (`/api/tailor/single/{job_id}` or JIT generate endpoints).
5. Apply using extension/manual flow.
6. Mark completion (`/api/sniper/complete` or `/api/profile/application_complete`).
7. Keep tracker up to date via `/api/tracker/{job_id}/status` as interview stages advance.
