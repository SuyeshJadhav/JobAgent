# JobAgent

JobAgent is a local-first FastAPI system for internship discovery, scoring, and application workflow automation. It fetches jobs from Simplify, direct ATS APIs, and Serper fallback search; then applies deterministic gates plus LLM scoring to shortlist opportunities. For shortlisted jobs, it can generate tailored one-page LaTeX resumes and cover letters, and expose payloads/answers for extension-assisted application flows.

## Quick Start

1. Create and activate a virtual environment.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies.

```powershell
pip install -r requirements.txt
scrapling install
playwright install chromium
```

3. Create environment file from template.

```powershell
Copy-Item .env.example .env
```

4. Start API + dashboard.

```powershell
uvicorn backend.main:app --reload
```

5. Trigger first scout run.

```powershell
curl -X POST http://127.0.0.1:8000/api/scout/run
```

Dashboard is served at `http://127.0.0.1:8000/dashboard`.

## Requirements

- Python: 3.10+ (runtime uses modern type syntax and is currently exercised on Python 3.12.6 in this repo)
- Ollama: required for local LLM mode (`llm_provider: ollama`)
- MiKTeX (or any `pdflatex` provider): required for resume/cover-letter PDF compilation
- Groq: optional, but required if using `llm_provider: groq` or Groq tailoring (`GROQ_API_KEY`)

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [SETUP.md](SETUP.md)
- [PIPELINE.md](PIPELINE.md)
- [CONFIGURATION.md](CONFIGURATION.md)
- [API.md](API.md)
- Existing design notes: [docs/DESIGN.md](docs/DESIGN.md), [docs/workflow.md](docs/workflow.md), [docs/research.md](docs/research.md)

## Tech Stack

| Area                  | Stack from Code                                                                       |
| --------------------- | ------------------------------------------------------------------------------------- |
| Backend API           | FastAPI, Uvicorn                                                                      |
| Core language         | Python                                                                                |
| Storage               | SQLite (`backend/tracked_jobs.db`), filesystem artifacts (`outputs/applications/...`) |
| Job discovery         | Simplify feed JSON + Greenhouse/Lever/Ashby APIs + Serper                             |
| Scraping              | scrapling (`DynamicFetcher`, `StealthyFetcher`)                                       |
| Scoring               | Deterministic pre-checks + OpenAI-compatible LLM client (Ollama/Groq)                 |
| Resume generation     | LaTeX template injection + `pdflatex` + `pypdf` page validation                       |
| Cover letters         | LLM generation + markdown + optional LaTeX PDF compile                                |
| Extension integration | FastAPI endpoints consumed by `extension/` scripts                                    |
