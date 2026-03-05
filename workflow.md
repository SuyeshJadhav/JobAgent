# JobAgent Workflow & Architecture Overview

## What We Have Done So Far
The project underwent a major structural migration aimed at turning it from a scattered set of local Python scripts into a robust, centralized FastAPI backend system. Following that, it was optimized to be easily setup removing reliance on external APIs.

1. **Dependency Management**: Created a strict `requirements.txt` to resolve environment errors (like the Playwright missing module crash) and streamline setup.
2. **Single Data Source of Truth (CSV Native)**: 
   - Eliminated the redundant SQLite (`scout_jobs.db`) database.
   - De-coupled the reliance on **Notion API** making it infinitely easier to start offline.
   - We now rely securely on a native `tracked_jobs.csv` tracking file. This allows standard data modification safely handled by apps like **Excel** or **Google Sheets** for visual manipulation, while maintaining full automated parsing ability behind the API!
   - Implemented a local JSON caching system (`job_details.json`) for storing full Job Descriptions without hitting tracker cell-size limits.
3. **Source Engine Migration**: 
   - Replaced unreliable web-scraping (JobSpy) with high-quality, pre-aggregated GitHub JSON data feeds (Simplify Internships/New Grad lists). 
   - Implemented sophisticated text-filtering mechanisms for seniority matching, role matching, and company blocking.
   - Added extensive configurable filtering via `settings.json` (hours posted, category blocking, and strict visa sponsorship checks).
4. **Backend Router Integration**:
   - **Scout Router (`scout.py`)**: Connected the Simplify feed to a local LLM which reads the `references/candidate_profile.md` directly. It scores the jobs and pushes viable ones into the `tracked_jobs.csv` as `shortlisted`.
   - **Tailor Router (`tailor.py`)**: Built an endpoint that pulls the shortlisted job from the spreadsheet, retrieves its local description, modifies the base LaTeX resume, compiles a bespoke PDF via `pdflatex`, generates a custom cover letter, and syncs the file paths back to the tracker file safely.
   - Implemented strict AI formatting constraint rules (selector prompting) to rewrite resume bullets, number hallucination validations, and automatic PDF one-page length truncation.
5. **Code Cleanup**: Safely deleted the entire legacy `scripts/` folder, completely unifying the application under the `backend/` FastAPI architecture.
6. **Google Sheets Integration & GitHub Sync**:
   - Built `sheets_manager.py` using `gspread` for direct Google Sheets API integration via a service account (`credentials.json`).
   - Added `batch_append_job_rows()` for efficient bulk inserts with URL-based deduplication (`get_existing_urls()`).
   - Created `/sync_github_jobs` endpoint (`tracking.py`) to fetch filtered jobs from SimplifyJobs GitHub repos and batch-add them to Google Sheets (or fallback Excel) automatically.
   - Falls back gracefully to a local `backend/tracked_jobs.xlsx` when Google credentials are unavailable.
7. **Excel Formatter (`excel_formatter.py`)**:
   - Professional formatting with status-based color coding (e.g., green for Applied, amber for Shortlisted, red for Rejected).
   - Clickable "➜ Apply" button column with hyperlinks to the job application URL.
   - Frozen header row, auto-filters, and custom column widths for a dashboard-like experience.
   - Auto-formats after every sync; also available on-demand via `POST /format_excel`.
8. **Sniper Browser Extension**:
   - Lean `content.js` that injects floating buttons ("🎯 Snipe Answers" and "🏁 Mark Applied") on job application pages.
   - Scrapes only behavioral/complex textarea questions (filtering out standard identity fields via a blocklist).
   - Sends questions + URL to the Sniper backend (`/api/sniper/answer`) which matches the job, retrieves the JD, loads the user profile, and uses an LLM to generate tailored answers.
   - React-safe DOM injection for filling fields and Base64 resume injection via the DataTransfer API.
   - Manual Job ID fallback UI when the URL can't be auto-matched to a tracked job.
   - Mark Applied flow (`/api/sniper/complete`) updates the CSV status and cleans up generated PDFs.
9. **Vector Cache (ChromaDB)**:
   - Upgraded from simple JSON caching to a semantic vector cache using ChromaDB for profile Q&A.
   - Performs similarity-based lookups (distance threshold 0.4) to reuse previously generated answers for similar questions.
10. **Resume Scoring & Auto-Attach**:
    - The Sniper endpoint evaluates the resume score against the job and automatically attaches the best resume (tailored PDF or default) as Base64 in the response.

---

## Current Application Workflow

The job application pipeline is broken into modular API phases:

### Phase 1: Scouting (`POST /api/scout/run`)
- **Action**: Reads the candidate profile and configurations.
- **Fetch**: Pulls live JSON listings from the Simplify repository.
- **Filter**: Before any LLM processing, the jobs are strictly pruned using:
  - Age limits (e.g., posted in the last 72 hours).
  - Visa sponsorship checks (e.g., blocking non-sponsoring companies).
  - Category blocking (e.g., removing Hardware, Legal, Finance jobs).
  - Keyword and seniority checks (removing senior roles or blocked domains).
- **Score**: The remaining jobs are evaluated by an LLM against a simple rule-list (`candidate_profile.md`) to yield a score out of 10. This ensures the job is relevant (e.g., actually a Software Engineering role) before wasting time making a resume for it.
- **Track**: Jobs scoring above the configured threshold are appended gracefully into `tracked_jobs.csv` with a status of `shortlisted`. The full bulky Job Description text is saved to the local `outputs/applications/{job_id}/job_details.json`.

### Phase 2: Tailoring (`POST /api/tailor/{job_id}`)
- **Action**: Targets a specific `job_id` stored in your spreadsheet tracking file.
- **Verify**: Confirms the job exists, status is `shortlisted`, and score meets the threshold.
- **Resume Tailoring**: 
  - Validates which sections to bypass (like Header, Summary, Education).
  - Uses strict selector LLM prompting to extract exact keywords from the job description and inject them into matched sections (like Projects and Experience), without making up external tools or altering original metrics.
  - Generates a bespoke PDF via `pdflatex` applying programmatic truncation algorithms to strictly enforce the 1-page aesthetic constraint.
- **Cover Letter Generation**: Synthesizes a tailored markdown cover letter using context bank notes.
- **Track**: Updates the job status inside `tracked_jobs.csv` to `tailored` and attaches the local filesystem paths mapping your generated Resume and Cover Letter.

### Phase 3: Application via Sniper Extension
- The Sniper browser extension injects floating UI buttons on any job application page.
- **"🎯 Snipe Answers"**: Scrapes behavioral questions from the page, sends them to `/api/sniper/answer`, and auto-fills the form fields with LLM-generated, profile-tailored answers. Also injects the best-match resume PDF into file upload inputs.
- **"🏁 Mark Applied"**: Sends the current URL to `/api/sniper/complete`, which updates the job status to `applied` in `tracked_jobs.csv` and cleans up temporary PDF files.
- If the URL can't be auto-matched, a manual Job ID input fallback appears.

### Phase 4: GitHub Sync & Tracking (`POST /sync_github_jobs`)
- **Fetch**: Pulls filtered job listings from SimplifyJobs GitHub repositories (internship + new grad).
- **Dedup**: Checks existing URLs in Google Sheets (or fallback Excel) to skip duplicates.
- **Batch Insert**: Adds new jobs via `batch_append_job_rows()` using a single `append_rows` API call.
- **JD Storage**: Saves each job description as a `.txt` file in `backend/saved_jds/` for future reference.
- **Auto-Format**: Runs the Excel formatter post-sync so the spreadsheet always looks polished.

### Phase 5: Status Tracking & Visualization
- **Google Sheets**: Primary tracker when `credentials.json` is present — jobs are added to the "JobAgent Tracker" spreadsheet.
- **Excel Fallback**: `backend/tracked_jobs.xlsx` with professional formatting:
  - Color-coded rows by status (Saved, GitHub Source, Shortlisted, Applied, Interview, Offer, Rejected).
  - Clickable "➜ Apply" buttons linking to each job's application URL.
  - Frozen headers, auto-filters, and styled typography.
- **On-demand formatting**: `POST /format_excel` re-applies styling to the Excel tracker at any time.
- Status workflow: `pending_scrape` → `shortlisted` → `tailored` → `applied` → `interviewing` / `rejected` / `offer`.

---
*Note: This architecture file will be updated organically as the project evolves with new frontend clients, auto-apply automation features, and interview prep agents.*
