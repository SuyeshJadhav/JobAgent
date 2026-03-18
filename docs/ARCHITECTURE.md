# Architecture

## System Overview

JobAgent is organized around three operational layers.

1. Discovery layer: collects jobs from Simplify, ATS APIs, and Serper fallback, deduplicates them, then runs scrape/filter/score gates.
2. Generation layer: tailors resume content, injects sections into LaTeX templates, compiles PDFs, and generates cover letters.
3. Tracking layer: stores lifecycle state in SQLite, persists per-job artifacts on disk, and exposes tracker/status APIs.

## Module Map (backend/)

### Entry

- `backend/main.py`: FastAPI application bootstrap, CORS setup, router mounting, and `/dashboard` static mount.

### Config

- `backend/config/config.py`: environment-backed constants (`SERPER_API_KEY`, `COMPANY_SLUGS_FILE`).

### Routers

- `backend/routers/__init__.py`: package marker (empty file).
- `backend/routers/apply.py`: serves apply payload (`resume_path`, `cover_letter_path`) for a tracked job.
- `backend/routers/profile.py`: profile file read/write, autofill bridge, and application completion tracking/cleanup.
- `backend/routers/scout.py`: scout trigger, jobs retrieval, URL check, rescoring, and organic tracking endpoints.
- `backend/routers/settings.py`: settings file read/write and LLM connectivity test endpoint.
- `backend/routers/sniper.py`: LLM application answer generation plus post-apply artifact shredding endpoint.
- `backend/routers/tailor.py`: JIT resume/cover generation, single-job tailoring, and batch tailoring trigger endpoints.
- `backend/routers/tracker.py`: tracker stats, job listing, status patching, and delete endpoints.
- `backend/routers/tracking.py`: legacy tracking routes; currently logs "Google Sheets sync not available" after sheets manager removal.

### Services

- `backend/services/ats_clients.py`: ATS and Serper clients (`fetch_ats_jobs`, `fetch_serper_fallback_jobs`) with role/location filtering.
- `backend/services/bullet_validator.py`: generated bullet/PDF validators for ownership language, numbers, tools, and length constraints.
- `backend/services/cover_letter.py`: cover-letter generation, hallucination cleanup, markdown output, and optional LaTeX PDF compile.
- `backend/services/db_tracker.py`: SQLite schema/init, CRUD, transition guards, stats, and job details filesystem persistence.
- `backend/services/fact_selector.py`: deterministic experience section builder and weak-bullet deterministic rewrite helpers.
- `backend/services/jd_scraper.py`: multi-strategy JD scraper (dynamic, stealth fallback, ATS selectors, heading heuristics, block detection).
- `backend/services/job_sources.py`: Simplify source fetch + top-level aggregation of simplify/ATS/Serper sources.
- `backend/services/llm_client.py`: settings loader and OpenAI-compatible client factory for Ollama/Groq.
- `backend/services/profile_manager.py`: markdown candidate profile parser for scorer-facing summary fields.
- `backend/services/profile_rag.py`: fast-path + vector cache + LLM fallback form-answer pipeline.
- `backend/services/resume_generators.py`: JD keyword extraction, project ranking, section rewriting, and skills tailoring utilities.
- `backend/services/resume_manager.py`: resume-fit scoring and default-vs-tailored resume selection helper.
- `backend/services/resume_tailor.py`: end-to-end tailoring pipeline (`run_tailor`) and LaTeX compile/recovery orchestration.
- `backend/services/scorer.py`: deterministic pre-checks + rubric-driven LLM scoring + sponsorship post-adjustment.
- `backend/services/scout_processor.py`: asynchronous scout processing gates and organic job upsert/scoring flow.

### Utils

- `backend/utils/job_normalizer.py`: job-type normalization, date normalization, deduplication, and normalized job record construction.
- `backend/utils/latex_parser.py`: marker-section parser, template injection, aux-file cleanup, and LaTeX escaping helper.
- `backend/utils/latex_utils.py`: LaTeX sanitation, bullet payload parsing, ownership phrase normalization, and text trimming.
- `backend/utils/profile_loader.py`: shared loader for profile markdown files.
- `backend/utils/reference_loader.py`: shared loader for reference assets (`main.tex`, `context_bank.toml`, profile/template docs).
- `backend/utils/text_cleaner.py`: title/location/dealbreaker filters, JD trimming, safe filenames, garbage metadata checks.
- `backend/utils/url_matcher.py`: URL normalization/matching and deterministic job ID generation.

### Non-Python backend files

- `backend/config/settings.json`: runtime settings source consumed by `get_settings()`.
- `backend/tracked_jobs.db`: primary SQLite tracker database file.
- `backend/tracked_jobs.xlsx`: Excel tracker artifact retained in repository.

### Environment source

- Root `.env`: single supported environment-variable source.
- `backend/.env`: deprecated and not used by startup path anymore.

## Data Flow: Fetch to Output Folder

1. `POST /api/scout/run` calls `fetch_all_scout_sources` from `backend/services/job_sources.py`.
2. Source jobs are merged and deduplicated via `deduplicate_jobs`.
3. New jobs are inserted into SQLite with status `found` using `add_job`.
4. `ScoutProcessor.process_jobs_bg` runs gate checks and scoring; statuses become `shortlisted` or `rejected`.
5. For each processed job, `save_job_details` writes `job_details.json` under:
   - `outputs/applications/{YYYY-MM-DD}/{Company}-{Title}-{short_id}/job_details.json`
6. Tailoring routes call `run_tailor` and `run_cover_letter`, which write artifacts in the same folder:
   - `resume.tex`, compiled resume PDF, `cover_letter.md`, optional cover-letter PDF.

## Scoring System

Scoring behavior comes from `backend/services/scorer.py` and the scout gating path in `backend/services/scout_processor.py`.

### Pre-LLM deterministic checks

- Quant firm cap: known quant companies return score `2` immediately.
- Seniority reject: `senior/staff/principal/lead/manager/director/vp/head` titles return score `0` (except intern titles).

### LLM deduction rubric (base-10)

The scoring prompt in `_build_scoring_prompt` enforces this sequence:

1. Auto-reject to `0` for explicit citizenship/security-clearance requirements or senior roles.
2. Experience gap deduction (`-2` for 3-4 years, `-3` for 5+ years).
3. Required-tech mismatch deduction (capped at `-3`).
4. Domain penalty (quant/legal/non-tech/finance patterns).
5. Role relevance bonus (`+1` exact role match, `+1` AI/ML/LLM work).

Output contract includes JSON fields: `company`, `title`, `reasoning`, `score`, `strategy`.

### Post-LLM adjustment

- If `job.is_sponsored` and settings `visa_status` is `prefer_sponsorship`, score gets `+1` (capped to 10).

### Shortlist threshold

- In `ScoutProcessor`, shortlist decision is `score >= int(settings['score_threshold'])`.
- Current `backend/config/settings.json` has `system.score_threshold: 6`.

## Resume Tailoring System

`run_tailor` in `backend/services/resume_tailor.py` executes:

1. Build job output directory and persist `job_details.json`.
2. Load references via `load_references` (`main.tex`, context bank, profile/template docs).
3. Parse marker sections using `parse_marker_sections`.
4. Extract JD keywords using `extract_jd_keywords`.
5. Generate tailored section content via `generate_tailored_content`.
6. Sanitize tailored text via `_sanitize_tailored_content`.
7. Build ranked projects section via `build_ranked_projects_section` and replace template projects section.
8. Optional deterministic rewrites controlled by `deterministic_project_bullets` setting:
   - weak project bullet deterministic rewrite,
   - deterministic experience section rebuild from context bank.
9. Compile LaTeX with `_compile_latex_to_pdf`.
   - first compile,
   - retry with bullet trimming,
   - retry with project-density tightening,
   - retry with layout compression.
10. Run `_validate_generated_resume_artifacts` and persist warnings into `job_details.json`.

## Key Design Decisions (as evidenced in code)

- Filesystem-first artifacts: `db_tracker.save_job_details` stores full job JSON in `outputs/applications/...` so tailoring can run from local details even after DB updates.
- Forward-only status integrity: `_can_transition` in `db_tracker.py` prevents regressions (except side branches), reducing accidental lifecycle corruption.
- Scrape robustness over single selector: `jd_scraper.py` tries ATS selectors, heading heuristics, then body fallback; this is explicitly coded to handle heterogeneous ATS HTML.
- Guardrails before polish: `resume_generators.rewrite_bullets_with_validation` rejects numeric hallucinations and falls back to original text if retries fail.
- 1-page recovery strategy: `_compile_latex_to_pdf` retries with trimming/tightening/compression before returning warning, prioritizing stable output over silent failure.
- Deletion-safe apply completion: `sniper.py` updates status first, then shreds artifact directories matched by `job_id`, preserving high-level tracker history while removing generated files.
