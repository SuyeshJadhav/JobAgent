# JobAgent

## 1. What is JobAgent

JobAgent helps you find internship jobs, score them, and keep them organized in one place. It can also generate a tailored resume PDF and cover letter for a specific job when you ask for it. Everything runs locally with your FastAPI backend plus a browser extension workflow.

## 2. Features

- Finds jobs from multiple sources (Simplify feed, ATS APIs, and Serper queries)
- Filters jobs for US/Remote and role keyword match
- Tracks jobs in local SQLite
- Scores jobs with a rule-based + LLM pipeline
- Generates tailored LaTeX resume PDFs on demand
- Generates cover letters on demand
- Supports browser autofill/sniper flow for application answers
- Optional Google Sheets sync helper for job rows
- Dashboard UI to run scout, tailor, and track status

## 3. Installation

### Prerequisites

- Python 3.10+
- Node.js
  - TODO: The current frontend is static HTML/JS and does not require npm build steps in this repo.

### Step-by-step setup

1. Clone repo and open folder.

```bash
git clone <your-repo-url>
cd JobAgent
```

2. Create and activate a Python virtual environment.

```bash
python -m venv .venv
.venv\Scripts\activate
```

3. Install Python dependencies.

```bash
pip install -r requirements.txt
```

4. Create backend/.env file.

Exact template:

```env
SERPER_API_KEY=your_serper_api_key_here
```

5. Start backend.

```bash
python -m uvicorn backend.main:app --reload
```

6. Open dashboard.

- http://localhost:8000/dashboard

## 4. Configuration

### backend/config/config.py keys

Current keys in this file are:

- SERPER_API_KEY
  - Read from environment variable SERPER_API_KEY
  - Used for Serper search calls
- COMPANY_SLUGS_FILE
  - Name of the slug file used by ATS API source loader
  - Default value is company_slugs.json in project root

### company_slugs.json

This file tells JobAgent which companies to query in each ATS type:

- greenhouse list
- lever list
- ashby list

To add a company:

1. Pick the right ATS list.
2. Add the company slug string to that list.
3. Save file and run scout again.

Reference for internship listings and employer context:

- https://github.com/SimplifyJobs/Summer2026-Internships

TODO: Slugs themselves come from each company ATS board URL pattern, not directly from the Simplify repo code.

## 5. Troubleshooting

### I see 0 jobs

- Check SERPER_API_KEY in backend/.env
- Check company_slugs.json has real entries in greenhouse, lever, and ashby
- Check backend/config/settings.json role keyword and job_types settings

### Resume tailor is not working

- Check your LLM configuration
- TODO: Current code reads LLM provider/model/key from backend/config/settings.json (for Groq) and not from .env directly.

### App will not start

- Confirm Python version is 3.10+
- Confirm Node.js is installed
- Reinstall dependencies: pip install -r requirements.txt
- Start with: python -m uvicorn backend.main:app --reload

### Jobs are not from USA

- Source filters in job_sources.py enforce US/Remote checks per source
- Serper request currently sends gl="us" and location="United States"
- TODO: These Serper parameters are hardcoded in backend/services/job_sources.py, not in backend/config/config.py
