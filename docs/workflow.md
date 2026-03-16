# WORKFLOW

## 1. Architecture overview

```text
                       +-----------------------------+
                       |  company_slugs.json        |
                       |  backend/config/settings   |
                       +-------------+--------------+
                                     |
                                     v
+-------------+    /api/scout/run   +---------------------------+
| React Front | -------------------> | FastAPI (backend/main.py)|
| (TODO: see  |                      | Routers + Services       |
| note below) | <------------------- | /api/tracker /api/tailor |
+------+------+     JSON responses   +------------+-------------+
       |                                           |
       |                                           |
       |                               write/read  v
       |                              +------------------------+
       |                              | db_tracker (SQLite)    |
       |                              | backend/tracked_jobs.db|
       |                              +-----------+------------+
       |                                          |
       |                                          | save details/resumes
       |                                          v
       |                              +------------------------+
       |                              | outputs/applications   |
       |                              | job_details.json, PDF  |
       |                              +------------------------+
       |
       | trigger buttons                         +---------------------+
       +---------------------------------------> | Excel/Sheets Sync   |
                                                 | sheets_manager.py    |
                                                 +---------------------+

Job source subsystem inside FastAPI:
  [Simplify feed] + [ATS APIs: Greenhouse/Lever/Ashby] + [Serper query source]
                               |
                               v
                        merged list -> deduplicate -> DB insert
                               |
                               v
                      ScoutProcessor background scoring

Resume subsystem inside FastAPI:
  shortlisted job -> run_tailor() -> section rewrite -> pdflatex -> PDF

APScheduler component:
  TODO: No APScheduler implementation is present in backend code right now.

React frontend component:
  TODO: Current frontend is static HTML + vanilla JavaScript in frontend/index.html and frontend/app.js,
  not a React app.
```

## 2. How each job source works

### SimplifyJobs GitHub feed

Code path: backend/services/job_sources.py, fetch_simplify_jobs().

- Fetch URL used:
  - https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json
- Parsed fields per listing:
  - title
  - company (company_name fallback company)
  - url
  - location (location fallback first entry of locations)
  - date_posted (date_posted fallback date_updated)
- Filters applied:
  - apply link must exist
  - title must contain configured role keyword (case-insensitive)
  - location must be US/Remote policy:
    - accepts location containing usa, united states, u.s., remote
    - accepts empty/null location

### Direct ATS APIs (Greenhouse, Lever, Ashby)

Code path: backend/services/job_sources.py, fetch_ats_jobs().

- Company slugs source:
  - company_slugs.json in project root
  - loaded by \_load_company_slugs() using COMPANY_SLUGS_FILE from backend/config/config.py
- Calls are parallelized with ThreadPoolExecutor.

Endpoints used:

- Greenhouse:
  - GET https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true
  - fields used: jobs[].title, jobs[].absolute_url, jobs[].location.name
- Lever:
  - GET https://api.lever.co/v0/postings/{company_slug}?mode=json
  - fields used: [].text, [].hostedUrl, [].categories.location
- Ashby:
  - POST https://api.ashbyhq.com/posting-api/job-board/{company_slug}
  - request body: {"jobPostings": true}
  - fields used: jobPostings[].title, jobPostings[].jobUrl, jobPostings[].locationName

Filters per ATS result:

- apply URL must exist
- title contains configured role keyword
- location passes US/Remote policy (same helper as Simplify source)

### Serper fallback source

Code path: backend/services/job_sources.py, fetch_serper_fallback_jobs().

- Uses \_search_serper() with:
  - gl="us"
  - location="United States"
- Query templates currently generated:
  - "{role_keyword}" site:myworkdayjobs.com
  - "{role_keyword}" site:icims.com
  - "{role_keyword}" site:smartrecruiters.com
- Quota behavior:
  - function has max_queries parameter (default 5)
  - currently only 3 query templates exist, so max actual queries/run is 3
- Result handling:
  - blocks aggregator/search URLs
  - runs ATS/domain heuristics
  - converts links into normalized job records

TODO: Despite function name "fallback", this source is currently run on every scout call via fetch_all_scout_sources(), not conditionally triggered.

## 3. Data flow from fetch to DB

Current runtime flow from /api/scout/run:

1. FastAPI router receives /api/scout/run.
2. normalize_job_types() validates configured job_types.
3. fetch_all_scout_sources() runs:
   - Simplify feed fetch + filter
   - ATS API fetch + filter (parallel)
   - Serper source fetch + heuristic filter
4. All source jobs are merged into one list.
5. deduplicate_jobs() runs on merged list.
6. For each deduped job not already in SQLite (get_job_by_id):
   - add_job() inserts row with status found, score 0
7. If any new jobs were inserted, background task process_jobs_bg() starts.
8. Background processing then scrapes JD, sanitizes text, scores, and updates status/score/reason.

SQLite details:

- DB file: backend/tracked_jobs.db (fallback tracked_jobs.db outside repo root)
- Access layer: backend/services/db_tracker.py
- Table: jobs with lifecycle fields and artifact paths
- CSV migration is still present as one-time compatibility logic if tracked_jobs.csv exists.

WAL mode:

- TODO: WAL mode is not configured in current db_tracker.py (no PRAGMA journal_mode=WAL found).

## 4. Scoring system

What exists in code today (backend/services/scorer.py + scout_processor.py):

### Stage A: deterministic pre-checks

- Quant firm cap pre-check in score_job(): known quant company names are auto-capped to score 2.
- Seniority pre-check in score_job(): senior/staff/lead/manager/director titles auto-rejected to score 0 (except intern wording).
- Additional deterministic gates in ScoutProcessor before scoring:
  - blocked title terms
  - non-target location checks
  - dealbreaker term checks from JD text
  - protected intern-like titles can auto-shortlist with score 10

### Stage B: LLM deduction rubric scoring

- \_build_scoring_prompt() defines a base-10 deduction rubric with:
  - auto-reject conditions
  - experience gap penalties
  - core stack mismatch penalties
  - domain penalties
  - role relevance bonus
- model call path:
  - \_execute_llm_scoring() with JSON response mode when supported
  - parse_llm_json_response() with regex fallback

### Stage C: post-adjustment

- sponsorship bonus (+1) when is_sponsored is true and visa preference is prefer_sponsorship.

Domain caps and inflation control:

- Quant firms are explicitly capped via deterministic pre-check to reduce finance-domain score inflation.
- The LLM rubric also includes domain penalties for quant/legal/non-tech/finance contexts.

Requested "3-stage hybrid deterministic -> keyword match -> borderline LLM" mapping:

- TODO: There is no separate explicit keyword-match scoring stage before LLM.
- TODO: There is no explicit "only borderline goes to LLM" branch; LLM scoring is used by default after pre-checks.

## 5. Resume tailoring pipeline

Code path: backend/routers/tailor.py + backend/services/resume_tailor.py + backend/services/resume_generators.py + backend/utils/latex_parser.py.

### Lazy/on-demand trigger

- Primary JIT endpoint: /api/tailor/generate.
- It resolves by job_id or URL, ensures JD exists (or scrapes it), then runs tailoring only when requested.
- If an existing PDF already exists for the job, the endpoint reuses it instead of regenerating.

### Section-aware formatting

- parse_marker_sections() reads %% BEGIN ... %% / %% END ... %% marker blocks.
- generate_tailored_content() applies section-specific behavior:
  - skip pass-through sections (header/summary/education)
  - special skills-mode rewrite for SKILLS
  - bullet-mode rewrite for EXPERIENCE/PROJECTS
- inject_content_into_tex() injects rewritten text only inside marker regions.

### imp macro handling

- In rewrite_bullets() prompt rules, model is told: NEVER use the old \imp macro; use \textbf instead.
- TODO: There is no "\imp preservation" mechanism in current code. The behavior is the opposite (discourage \imp usage).

### Number hallucination validation with retry

- rewrite_bullets_with_validation() extracts numbers from trusted context + original text.
- If rewritten output introduces unseen numbers, it retries once with stricter warning.
- On repeated failure, it falls back to original section text.

### Technical keyword filtering / domain-bleed controls

- rewrite_bullets() strict prompt forbids inventing tools, projects, or metrics.
- It explicitly instructs ignoring keywords that require adding unsupported technologies.
- rewrite_skills_section() constrains output to skills listed in profile/skills.md and prunes to 4-5 relevant categories.
- This combination is the current domain-bleed prevention mechanism.
