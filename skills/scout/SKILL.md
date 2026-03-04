---
name: scout
description: >
  Finds fresh job listings daily based on target roles defined in candidate_profile.md.
  Use this skill when the user asks to find jobs, run the scout, check new listings,
  or start the pipeline. Does NOT use the resume to search — searches by role title only.
---

# Scout Skill

Finds jobs by role title using JSearch API. Saves new listings to CSV.

---

## Inputs
- Target roles → from `references/candidate_profile.md`
- Filters: level (intern/new grad), location preference

## What to Search
Build queries from candidate's target roles. Examples:
```
"AI Engineer intern"
"ML Engineer new grad"
"LLM Engineer remote"
"Applied Scientist entry level"
```

## Steps

1. Load `references/candidate_profile.md` to get target roles + preferences
2. For each role, call JSearch API with `date_posted: today`
3. For each result, check CSV — skip if `job_id` already exists
4. Save new jobs to DB with status = `found`
5. Pass new jobs to `scorer` skill

## Output Format (CSV row)
```
job_id, title, company, location, apply_link, description, score, reason, found_at, applied_at, status, resume_path, cover_letter_path, notes, last_updated
```

## API Details
- API: JSearch (RapidAPI)
- Key env var: `JSEARCH_API_KEY`
- Max results per query: 10
- Only fetch `date_posted: today` to avoid stale listings

## API Integration
Run: `backend/services/job_sources.py` or trigger `POST /api/scout/run`

## Rules
- Never search using resume content — role titles only
- Always deduplicate by `job_id`
- Log every run with timestamp
