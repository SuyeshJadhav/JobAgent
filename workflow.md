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
   - **Recent Updates**: Added extensive configurable filtering via `settings.json` (hours posted, category blocking, and strict visa sponsorship checks).
4. **Backend Router Integration**:
   - **Scout Router (`scout.py`)**: Connected the Simplify feed to a local LLM which reads the `references/candidate_profile.md` directly. It scores the jobs and pushes viable ones into the `tracked_jobs.csv` as `shortlisted`.
   - **Tailor Router (`tailor.py`)**: Built an endpoint that pulls the shortlisted job from the spreadsheet, retrieves its local description, modifies the base LaTeX resume, compiles a bespoke PDF via `pdflatex`, generates a custom cover letter, and syncs the file paths back to the tracker file safely.
   - **Recent Updates**: Implemented strict AI formatting constraint rules (selector prompting) to rewrite resume bullets, number hallucination validations, and automatic PDF one-page length truncation.
5. **Code Cleanup**: Safely deleted the entire legacy `scripts/` folder, completely unifying the application under the `backend/` FastAPI architecture.

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

### Phase 3: Application & Status Sync
- The user interacts directly with `tracked_jobs.csv` offline via Excel, or through future frontend components to view tailored applications.
- After applying via the provided link, the user (or future automation) transitions the job status in the Sheet to `applied`, `interviewing`, `rejected`, or `offer`.

---
*Note: This architecture file will be updated organically as the project evolves with new frontend clients, auto-apply automation features, and interview prep agents.*
