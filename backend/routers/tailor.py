from backend.utils.url_matcher import find_job_by_url
import base64
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
import asyncio

from backend.services.resume_tailor import run_tailor
from backend.services.cover_letter import run_cover_letter
from backend.services.db_tracker import (
    get_job_by_id, update_job, load_job_details, get_jobs, save_job_details
)
from backend.services.llm_client import get_settings
from backend.services.jd_scraper import scrape_full_jd

router = APIRouter(prefix="/api/tailor", tags=["tailor"])
OUTPUT_DIR = Path(__file__).parent.parent.parent / "outputs" / "applications"


class GenerateRequest(BaseModel):
    job_id: Optional[str] = None
    url: Optional[str] = None


@router.post("/generate")
def generate_tailored_resume(payload: GenerateRequest):
    """
    JIT (Just-In-Time) resume tailoring endpoint.
    Accepts a job_id or url, runs the full tailor pipeline,
    and returns the PDF as base64.
    """
    # 1. Resolve job
    jobs = get_jobs()
    matched_job = None

    if payload.job_id:
        matched_job = get_job_by_id(payload.job_id)
    elif payload.url:
        matched_job = find_job_by_url(jobs, payload.url)

    if not matched_job:
        raise HTTPException(
            status_code=404, detail="Job not found in tracked jobs.")

    job_id = matched_job["job_id"]

    # 2. Load full description
    details = load_job_details(job_id)
    if not details:
        raise HTTPException(
            status_code=404, detail="Job details file missing. Re-run scout or organic track.")

    desc = details.get("description", "")
    if not desc or len(desc) < 100:
        print(
            f"[TAILOR JIT] description missing for {job_id}, invoking scrapling...")
        try:
            desc = asyncio.run(scrape_full_jd(
                matched_job.get("apply_link", "")))
            if desc and desc != "SCRAPE_BLOCKED":
                matched_job["description"] = desc
            else:
                raise HTTPException(
                    status_code=400, detail="JD length < 100 and Scrape failed or was blocked.")
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to fetch JD missing text: {e}")
    else:
        matched_job["description"] = desc

    # 3. Check if a PDF already exists (skip re-tailoring)
    existing_dir = None
    if OUTPUT_DIR.exists():
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir():
                details_file = d / "job_details.json"
                if details_file.exists():
                    import json
                    try:
                        with open(details_file, encoding="utf-8") as f:
                            dj = json.load(f)
                        if dj.get("job_id") == job_id:
                            pdfs = list(d.glob("*.pdf"))
                            if pdfs:
                                existing_dir = d
                                break
                    except Exception:
                        pass

    pdf_path = None
    if existing_dir:
        pdfs = list(existing_dir.glob("*.pdf"))
        if pdfs:
            pdf_path = pdfs[0]

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
    threshold = int(settings.get("score_threshold", 6))
    if int(job.get("score", 0)) < threshold:
        raise HTTPException(
            status_code=400, detail="Job score below threshold")

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
