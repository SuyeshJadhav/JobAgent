from backend.utils.url_matcher import find_job_by_url
import base64
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
import asyncio
import json
import tempfile
import shutil
from uuid import uuid4

from backend.services.resume_tailor import run_tailor
from backend.services.cover_letter import run_cover_letter
from backend.services.db_tracker import (
    get_job_by_id, update_job, load_job_details, get_jobs, save_job_details
)
from backend.services.llm_client import get_settings
from backend.services.jd_scraper import scrape_full_jd
from backend.services.threshold_policy import (
    normalize_score_to_percent,
    resolve_score_threshold,
    threshold_rejection_detail,
)

router = APIRouter(prefix="/api/tailor", tags=["tailor"])


OUTPUT_DIR = Path(__file__).parent.parent.parent / "outputs" / "applications"


class GenerateRequest(BaseModel):
    job_id: Optional[str] = None
    url: Optional[str] = None


class RemoteTailorRequest(BaseModel):
    """Request model for remote tailor endpoint (used by remote users with their own workspace)."""
    job_description: str
    company: str
    role: str
    candidate_name: str
    main_tex: str
    context_bank_toml: str
    candidate_profile: str
    cover_letter_template: str = ""
    groq_api_key: str = ""


def _resolve_job(payload: GenerateRequest) -> dict:
    """Resolve a tracked job from either job_id or URL payload fields."""
    jobs = get_jobs()
    matched_job = None

    if payload.job_id:
        matched_job = get_job_by_id(payload.job_id)
    elif payload.url:
        matched_job = find_job_by_url(jobs, payload.url)

    if not matched_job:
        raise HTTPException(
            status_code=404, detail="Job not found in tracked jobs.")

    return matched_job


def _load_or_scrape_description(job: dict, fail_context: str) -> dict:
    """Ensure job has a usable JD description (loads saved details or scrapes on demand)."""
    job_id = job["job_id"]
    details = load_job_details(job_id)
    if not details:
        raise HTTPException(
            status_code=404, detail="Job details file missing. Re-run scout or organic track.")

    desc = details.get("description", "")
    if not desc or len(desc) < 100:
        print(
            f"[{fail_context}] description missing for {job_id}, invoking scrapling...")
        try:
            desc = asyncio.run(scrape_full_jd(job.get("apply_link", "")))
            if desc and desc != "SCRAPE_BLOCKED":
                job["description"] = desc
                return job
            raise HTTPException(
                status_code=400, detail="JD length < 100 and Scrape failed or was blocked.")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to fetch JD missing text: {e}")

    job["description"] = desc
    return job


def _find_existing_file_for_job(job_id: str, filename: str) -> Optional[Path]:
    """Find an already-generated artifact by filename in the matching job output folder."""
    if not OUTPUT_DIR.exists():
        return None

    for details_file in OUTPUT_DIR.rglob("job_details.json"):
        try:
            with open(details_file, encoding="utf-8") as f:
                dj = json.load(f)
            if dj.get("job_id") != job_id:
                continue

            candidate = details_file.parent / filename
            if candidate.exists() and candidate.is_file():
                return candidate
        except Exception as e:
            print(f"[TAILOR JIT] Error checking {details_file}: {e}")
            continue

    return None


def _enforce_threshold_if_scored(job: dict):
    score_value = job.get("score")
    if score_value is None:
        return

    settings = get_settings()
    threshold = resolve_score_threshold(settings)
    normalized_score = normalize_score_to_percent(score_value)
    if normalized_score < threshold:
        raise HTTPException(
            status_code=400,
            detail=threshold_rejection_detail(
                normalized_score,
                threshold,
                "Job score below threshold",
            ),
        )


@router.post("/generate")
def generate_tailored_resume(payload: GenerateRequest):
    """
    JIT (Just-In-Time) resume tailoring endpoint.
    Accepts a job_id or url, runs the full tailor pipeline,
    and returns the PDF as base64.
    """
    # 1. Resolve job
    matched_job = _resolve_job(payload)
    job_id = matched_job["job_id"]
    _enforce_threshold_if_scored(matched_job)

    matched_job = _load_or_scrape_description(matched_job, "TAILOR JIT")

    # 3. Check if a PDF already exists (skip re-tailoring)
    pdf_path = None
    if OUTPUT_DIR.exists():
        # Search recursively for job_details.json to find the correct application folder
        for details_file in OUTPUT_DIR.rglob("job_details.json"):
            try:
                with open(details_file, encoding="utf-8") as f:
                    dj = json.load(f)
                if dj.get("job_id") == job_id:
                    # Look for ANY pdf in this same folder
                    pdfs = list(details_file.parent.glob("*.pdf"))
                    if pdfs:
                        # Prioritize the one mentioned in metadata if it exists
                        meta_resume = dj.get("resume_path")
                        if meta_resume:
                            # resume_path might be relative to project root or absolute
                            rp = Path(meta_resume)
                            # If it's relative like "outputs/...", make it absolute relative to project root
                            if not rp.is_absolute():
                                rp = OUTPUT_DIR.parent.parent / rp

                            if rp.exists() and rp.suffix == ".pdf":
                                pdf_path = rp
                                break

                        # Fallback to the first PDF found in the folder
                        pdf_path = pdfs[0]
                        break
            except Exception as e:
                print(f"[TAILOR JIT] Error checking {details_file}: {e}")
                continue

    if not pdf_path:
        # 4. Run the tailor pipeline
        tailor_result = run_tailor(matched_job)
        if tailor_result.get("status") == "error":
            raise HTTPException(status_code=500, detail=tailor_result.get(
                "error", "Tailoring failed"))
        pdf_path = Path(tailor_result.get("pdf_path", ""))

        # Update tracking status
        update_job(job_id, status="tailored", resume_path=str(pdf_path))

    if not pdf_path or not pdf_path.exists():
        raise HTTPException(
            status_code=500, detail="PDF generation failed — file not found.")

    # 5. Encode and return
    with open(pdf_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    return {
        "job_id": job_id,
        "resume_base64": b64,
        "filename": pdf_path.name,
    }


@router.post("/generate_cover_letter")
def generate_cover_letter(payload: GenerateRequest):
    """
    JIT cover-letter generation endpoint.
    Accepts a job_id or url, runs cover-letter pipeline,
    and returns the generated file content as base64.
    """
    matched_job = _resolve_job(payload)
    job_id = matched_job["job_id"]
    _enforce_threshold_if_scored(matched_job)

    matched_job = _load_or_scrape_description(matched_job, "COVER JIT")

    letter_path = _find_existing_file_for_job(job_id, "cover letter.md")

    if not letter_path:
        cover_result = run_cover_letter(matched_job)
        if cover_result.get("status") == "error":
            raise HTTPException(
                status_code=500,
                detail=cover_result.get(
                    "error", "Cover letter generation failed"),
            )

        cover_letter_path = cover_result.get("cover_letter_path", "")
        letter_path = Path(cover_letter_path) if cover_letter_path else None
        if letter_path:
            update_job(job_id, cover_letter_path=str(letter_path))

    if not letter_path or not letter_path.exists():
        raise HTTPException(
            status_code=500, detail="Cover letter generation failed — file not found.")

    with open(letter_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    return {
        "job_id": job_id,
        "cover_letter_base64": b64,
        "filename": letter_path.name,
    }


@router.post("/single/{job_id}")
def run_tailor_endpoint(job_id: str):
    """Runs the full tailor pipeline for a job by fetching its details from the tracking DB."""
    # 1. Get job from tracking DB
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=404, detail="Job not found in tracking DB")

    # 2. Load full description
    details = load_job_details(job_id)
    if not details:
        raise HTTPException(
            status_code=404, detail="Job details file missing. Re-run scout.")

    # 3. Merge description and validate
    desc = details.get("description", "")
    if not desc or len(desc) < 100:
        print(
            f"[TAILOR] description missing for {job_id}, invoking scrapling...")
        # Invoke scraper
        try:
            # run_tailor_endpoint is synchronous in FastAPI but requires await for scrapling
            desc = asyncio.run(scrape_full_jd(job.get("apply_link", "")))
            if desc and desc != "SCRAPE_BLOCKED":
                job["description"] = desc
                details["description"] = desc
                save_job_details(job)
                # Optional tracker update
                update_job(job_id, description=desc[:200] + "...")
            else:
                raise HTTPException(
                    status_code=400, detail="JD length < 100 and Scrape failed or was blocked.")
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to fetch JD missing text: {e}")
    else:
        job["description"] = desc

    # 4. Validate score
    settings = get_settings()
    threshold = resolve_score_threshold(settings)
    normalized_score = normalize_score_to_percent(job.get("score", 0))
    if normalized_score < threshold:
        raise HTTPException(
            status_code=400,
            detail=threshold_rejection_detail(
                normalized_score,
                threshold,
                "Job score below threshold",
            ),
        )

    # 5. Validate status
    if job.get("status") != "shortlisted":
        raise HTTPException(
            status_code=400, detail="Job not in shortlisted status")

    # 6. Call run_tailor
    tailor_result = run_tailor(job)
    resume_path = tailor_result.get("pdf_path", "")

    # 7. Call run_cover_letter
    cover_result = run_cover_letter(job)
    cover_letter_path = cover_result.get("cover_letter_path", "")

    output_folder = tailor_result.get(
        "output_dir", "") or cover_result.get("output_dir", "")

    # 8. Update tracking status
    update_kwargs = {}
    if resume_path:
        update_kwargs["resume_path"] = str(resume_path)
    if cover_letter_path:
        update_kwargs["cover_letter_path"] = str(cover_letter_path)

    update_job(job_id, status="tailored", **update_kwargs)

    # 9. Return
    return {
        "job_id": job_id,
        "status": "tailored",
        "resume_path": str(resume_path),
        "cover_letter_path": str(cover_letter_path),
        "output_folder": str(output_folder)
    }


@router.get("/outputs")
def list_outputs():
    if not OUTPUT_DIR.exists():
        return {"folders": []}

    folders = []
    for d in OUTPUT_DIR.iterdir():
        if d.is_dir():
            folders.append(d.name)
    return {"folders": folders}


async def _bg_run_pending():
    """
    Background task to tailor all shortlisted jobs concurrently.
    Uses asyncio.gather with a semaphore to limit parallel LLM/LaTeX work.
    """
    CONCURRENCY = 2  # Max parallel tailor jobs (LLM + pdflatex per job)
    semaphore = asyncio.Semaphore(CONCURRENCY)
    jobs = get_jobs(status="shortlisted")

    async def _tailor_one(job):
        async with semaphore:
            job_id = job.get("job_id", "?")
            try:
                print(f"[TAILOR_BATCH] Starting tailoring for {job_id}...")
                await asyncio.to_thread(run_tailor_endpoint, job_id)
                print(f"[TAILOR_BATCH] Finished tailoring for {job_id}")
            except Exception as e:
                print(f"[TAILOR_BATCH_ERROR] job {job_id}: {e}")

    await asyncio.gather(*[_tailor_one(job) for job in jobs])
    print(f"[TAILOR_BATCH] All {len(jobs)} jobs processed.")


@router.post("/run_pending")
async def run_pending(background_tasks: BackgroundTasks):
    """Trigger background tailoring for all jobs currently marked 'shortlisted'."""
    jobs = get_jobs(status="shortlisted")
    if not jobs:
        return {"message": "No shortlisted jobs pending tailoring", "count": 0}

    background_tasks.add_task(_bg_run_pending)
    return {
        "message": f"Triggered parallel tailoring for {len(jobs)} shortlisted jobs (concurrency={2}).",
        "count": len(jobs)
    }


@router.post("/remote")
async def remote_tailor(req: RemoteTailorRequest):
    """
    Remote tailor endpoint for users running JobAgent client-side.

    She provides her own LaTeX files, context, and Groq key.
    We tailor using her compute (or fallback to Ollama on this machine).
    Returns base64-encoded PDF + cover letter.
    """
    tmp = None
    try:
        # 1. Create isolated temp workspace
        tmp = Path(tempfile.gettempdir()) / f"jobagent_{uuid4().hex}"
        tmp.mkdir(parents=True, exist_ok=True)

        # 2. Write her files to temp workspace
        (tmp / "main.tex").write_text(req.main_tex, encoding="utf-8")
        (tmp / "context_bank.toml").write_text(req.context_bank_toml, encoding="utf-8")
        (tmp / "candidate_profile.md").write_text(req.candidate_profile, encoding="utf-8")
        if req.cover_letter_template:
            (tmp / "cover_letter_template.md").write_text(
                req.cover_letter_template, encoding="utf-8")

        # 3. Copy shared LaTeX commands if available
        shared_commands = Path(__file__).parent.parent.parent / \
            "references" / "custom-commands.tex"
        if shared_commands.exists():
            shutil.copy(shared_commands, tmp / "custom-commands.tex")

        # 4. Build job dict for tailor
        job = {
            "job_id": uuid4().hex[:12],
            "company": req.company,
            "title": req.role,
            "description": req.job_description,
        }

        # 5. Run tailor with her workspace + her key
        result = run_tailor(
            job=job,
            references_override=tmp,
            candidate_name=req.candidate_name,
            groq_api_key=req.groq_api_key if req.groq_api_key else None
        )

        if result.get("status") == "error":
            raise HTTPException(
                status_code=500,
                detail=f"Tailoring failed: {result.get('error', 'Unknown error')}"
            )

        # 6. Read PDF as base64
        pdf_path = Path(result["pdf_path"])
        if not pdf_path.exists():
            raise HTTPException(
                status_code=500,
                detail="PDF file not found after tailoring"
            )

        pdf_b64 = base64.b64encode(pdf_path.read_bytes()).decode()

        # 7. Read cover letter if generated
        cover_letter = ""
        cover_letter_path = result.get("cover_letter_path")
        if cover_letter_path:
            cl_path = Path(cover_letter_path)
            if cl_path.exists() and cl_path.is_file():
                cover_letter = cl_path.read_text(encoding="utf-8")

        return {
            "pdf_base64": pdf_b64,
            "cover_letter": cover_letter,
            "filename": f"{req.candidate_name}.pdf",
            "warnings": result.get("validation_warnings", [])
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[REMOTE TAILOR] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Cleanup temp directory
        if tmp and tmp.exists():
            try:
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass
