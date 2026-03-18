# Setup

## Prerequisites

- Python 3.10+ (codebase uses modern typing syntax and is currently exercised on Python 3.12.6)
- `pdflatex` in PATH (MiKTeX on Windows is the typical option)
- Ollama running locally if using `llm_provider = "ollama"`
- Optional Groq API key if using Groq provider/modes (`GROQ_API_KEY`)

## Install

1. Create and activate virtual environment.

```powershell
+python -m venv .venv
+.\.venv\Scripts\Activate.ps1
```

2. Install Python dependencies.

```powershell
pip install -r requirements.txt
```

3. Install scraper/browser runtime dependencies (required by comments in `requirements.txt`).

```powershell
scrapling install
playwright install chromium
```

## Configure .env and settings.json

### 1) Environment file

Create root `.env` from `.env.example`:

```powershell
Copy-Item .env.example .env
```

Variables actually read by code:

- `SERPER_API_KEY`: read by `backend/config/config.py` for Serper fallback search.
- `GROQ_API_KEY`: read by `backend/services/llm_client.py` for Groq client setup and tailor-client preference.

### 2) Application settings

Edit `backend/config/settings.json`.
Current file values in repo:

```json
{
  "candidate_name": "Suyesh Jadhav",
  "llm_provider": "ollama",
  "ollama_model": "qwen2.5:7b",
  "ollama_model_options": ["llama3.2", "gemma3:4b", "phi3:medium"],
  "ollama_base_url": "http://localhost:11434/v1",
  "csv_path": "tracked_jobs.csv",
  "job_types": ["software", "intern", "internship"],
  "_visa_status_options": "Valid values: 'requires_sponsorship' (only Yes/Offers), 'prefer_sponsorship' (all jobs, sponsored get +2), 'no_preference' (all jobs, no change)",
  "visa_status": "prefer_sponsorship",
  "hours_old": 24,
  "blocked_categories": [
    "Quantitative Finance",
    "Quant",
    "Finance",
    "Accounting",
    "Legal",
    "Marketing",
    "Sales",
    "Medical",
    "Clinical",
    "Hardware",
    "Mechanical Engineering",
    "Civil Engineering",
    "Electrical Engineering"
  ],
  "blocked_companies": [
    "Lensa",
    "Wiraa",
    "Best Job Tool",
    "Nxt Level",
    "FetchJobs.co",
    "Elevate Recruitment",
    "North Star Staffing",
    "hackajob",
    "RemoteHunter",
    "Jobs via Dice"
  ],
  "blocked_keywords": ["Staffing", "Recruitment", "Resource Group"],
  "deterministic_project_bullets": true,
  "system": {
    "score_threshold": 6
  }
}
```

## Run the API

```powershell
uvicorn backend.main:app --reload
```

Expected clean startup lines include:

- `Uvicorn running on http://127.0.0.1:8000`
- `Application startup complete.`

## Run first scout

Trigger scout:

```powershell
curl -X POST http://127.0.0.1:8000/api/scout/run
```

Inspect results:

```powershell
curl http://127.0.0.1:8000/api/scout/jobs
curl http://127.0.0.1:8000/api/tracker/stats
```

## Troubleshooting (from actual code paths)

- `Configuration file not found: ...settings.json`
  - Raised by `llm_client.get_settings()` when `backend/config/settings.json` is missing.

- `Groq API key is missing in .env (GROQ_API_KEY)`
  - Raised by `llm_client.get_llm_client()` when `llm_provider` is `groq` and key is absent.

- `Unknown llm_provider: ...`
  - Raised by `llm_client.get_llm_client()` and `llm_client.get_model_name()` for unsupported provider values.

- `pdflatex is not installed`
  - Returned by `resume_tailor._compile_latex_to_pdf()` and `cover_letter._compile_cover_letter_to_pdf()` when compiler is unavailable.

- Scout jobs rejected due to scraping
  - `ScoutProcessor` sets status `rejected` with reason `Scrape blocked by bot protection` or `Scrape failed to find JD text` when `scrape_full_jd` fails.

- Serper fallback not running
  - `ats_clients.fetch_serper_fallback_jobs()` logs warning and returns empty list when `SERPER_API_KEY` is empty.

- Tailor endpoint returns score/status errors
  - `tailor.run_tailor_endpoint` returns HTTP 400 when score is below threshold or status is not `shortlisted`.
