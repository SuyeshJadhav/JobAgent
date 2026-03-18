# Configuration

## Environment Variables (`.env`)

Environment variables read by code:

| Variable         | Read In                          | Purpose                                                             |
| ---------------- | -------------------------------- | ------------------------------------------------------------------- |
| `SERPER_API_KEY` | `backend/config/config.py`       | Enables Serper fallback search in `fetch_serper_fallback_jobs`.     |
| `GROQ_API_KEY`   | `backend/services/llm_client.py` | Required for Groq provider client and preferred tailor client path. |

Notes from code:

- `backend/config/config.py` loads root `.env` before resolving `SERPER_API_KEY`.
- `backend/services/llm_client.py` loads root `.env` for LLM key resolution.
- Root `.env` is the single supported env file.
- `backend/.env` is deprecated.

## `backend/config/settings.json` schema and current values

Current file is JSON (verbatim values from repository):

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

Field usage from code:

- `llm_provider`, `ollama_base_url`, `ollama_model`: used by `llm_client.py`.
- `groq_tailor_model` (optional): read in `get_tailor_client` with default `meta-llama/llama-4-scout-17b-16e-instruct`.
- `candidate_name`: used in `resume_tailor.py` output filename generation.
- `role_keyword`/`search_role`/`target_role`/`role`: consumed by `_get_role_keyword` in job source modules.
- `job_types`: consumed by scout route normalization path.
- `visa_status`: used for sponsorship score bonus in scorer.
- `deterministic_project_bullets`: toggles deterministic rewrite paths in resume tailoring.
- `system.score_threshold`: shortlist threshold loaded by scout processor.

## `candidate_profile.md` format (parser-backed)

`parse_candidate_profile` in `backend/services/profile_manager.py` expects markdown sections with bullet lists:

- `## Background`
- `## Target Roles`
- `## Preferences`

Parsing rules:

- only lines starting with `- ` are consumed,
- in `Background`, lines containing `Degree:` or `Experience:` are appended into `experience_level`,
- output is flattened to strings for scorer:
  - `target_roles`: comma-separated,
  - `skills`: `|` separated,
  - `preferences`: `|` separated.

Minimal parser-compatible example:

```markdown
## Background

- Degree: Master of Computer Science
- Experience: Full Stack Development
- Key Languages: Python, JavaScript

## Target Roles

- Software Engineer Intern
- AI Engineer Intern

## Preferences

- Location: US Remote
- Level: Internship
```

## `context_bank.toml` format

Loaded by `backend/utils/reference_loader.py` and consumed by `fact_selector.py`, `resume_generators.py`, and validators.

Observed structure in repository:

- `[[experience]]` blocks with keys like `company`, `role`, `dates`.
- Nested `[[experience.achievement]]` entries with:
  - `verb`, `what`, `tool`, `metric`, `outcome`, `narrative`.
- `[[project]]` blocks with keys like `name`, `stack`, `github_link`, `dates`, `summary`.
- Nested `[[project.achievement]]` entries with same achievement fields.
- `[[voice_samples]]` blocks (`sample`).
- `[numbers]` table containing named metrics.

Minimal shape:

```toml
[[experience]]
company = "Example Co"
role = "Software Engineer Intern"
dates = "Jan 2026 - Mar 2026"

  [[experience.achievement]]
  verb = "Built"
  what = "feature X"
  tool = "FastAPI"
  metric = "40%"
  outcome = "reduced latency"

[[project]]
name = "Project One"
stack = ["Python", "FastAPI"]
summary = "..."

  [[project.achievement]]
  verb = "Designed"
  what = "pipeline Y"
  tool = "Python"
  metric = "75ms"
  outcome = "faster processing"

[numbers]
latency = "75ms"
```
