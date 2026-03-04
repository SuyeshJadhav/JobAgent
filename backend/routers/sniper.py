import json
import re
import base64
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.csv_tracker import get_jobs, load_job_details, update_job
from backend.services.llm_client import get_llm_client, get_model_name, get_settings

router = APIRouter(prefix="/api/sniper", tags=["sniper"])

PROFILE_DIR = Path(__file__).parent.parent.parent / "profile"
def load_profile_file(filename: str) -> str:
    path = PROFILE_DIR / filename
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def normalize_url(url: str) -> str:
    if not url:
        return ""
    # Strip query params
    url = url.split("?")[0]
    # Remove trailing slash
    url = url.rstrip("/")
    # Ignore http/https
    url = url.replace("https://", "").replace("http://", "")
    return url

class AnswerRequest(BaseModel):
    url: Optional[str] = None
    job_id: Optional[str] = None
    questions: list[str]

@router.post("/answer")
def get_sniper_answers(payload: AnswerRequest):
    # 1. Look up url or job_id in tracked_jobs.csv based on matching
    jobs = get_jobs()
    matched_job = None
    
    if payload.job_id:
        for j in jobs:
            if j.get("job_id") == payload.job_id:
                matched_job = j
                break
    elif payload.url:
        norm_incoming = normalize_url(payload.url)
        for j in jobs:
            link = j.get("apply_link", "")
            if not link:
                continue
            norm_link = normalize_url(link)
            if norm_link == norm_incoming or norm_link in norm_incoming or norm_incoming in norm_link:
                matched_job = j
                break
                
    if not matched_job:
        raise HTTPException(status_code=404, detail="Job not found in tracked jobs. Provide job_id.")
        
    job_context = "No job description found."
    if matched_job:
        job_id = matched_job["job_id"]
        details = load_job_details(job_id)
        if details and "description" in details:
            job_context = details["description"]
            
    # 2. Get User Context
    profile_sections = []
    for filename in ["personal_info.md", "visa.md", "work_experience.md",
                     "projects.md", "education.md", "skills.md", "essay_bank.md"]:
        content = load_profile_file(filename)
        if content.strip():
            profile_sections.append(f"--- {filename} ---\n{content}")
    user_profile = "\n\n".join(profile_sections)
    
    # 3. Prompt LLM
    questions_json = json.dumps(payload.questions, indent=2)
    system_prompt = (
        "You are an expert job application assistant helping the user fill out behavioral and company-specific "
        "questions on a job application. "
        "I will provide the job description, my profile context, and a list of questions to answer. "
        "Return ONLY a valid JSON object where the keys are the EXACT questions provided, "
        "and the values are tailored, 2-3 sentence answers matching the profile to the job.\n\n"
        "Rules:\n"
        "- Provide a tailored 2-3 sentence answer for each question.\n"
        "- Do NOT invent information that contradicts the profile.\n"
        "- Return ONLY the JSON object — no explanation, no markdown backticks."
    )
    
    user_prompt = (
        f"=== JOB DESCRIPTION ===\n{job_context}\n\n"
        f"=== MY PROFILE ===\n{user_profile}\n\n"
        f"=== QUESTIONS TO ANSWER ===\n{questions_json}\n\n"
        "Return the JSON object now."
    )
    
    try:
        client = get_llm_client()
        model = get_model_name()
        
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=2000,
        )
        raw = resp.choices[0].message.content.strip()
        
        llm_answers = None
        try:
            llm_answers = json.loads(raw)
        except json.JSONDecodeError:
            pass
            
        if llm_answers is None:
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if json_match:
                try:
                    llm_answers = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass

        if llm_answers is None:
            brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if brace_match:
                try:
                    llm_answers = json.loads(brace_match.group(0))
                except json.JSONDecodeError:
                    pass
                    
                    
        response_payload = llm_answers if (llm_answers and isinstance(llm_answers, dict)) else {q: "Could not generate answer." for q in payload.questions}
        
        # Check for resume injection
        if matched_job:
            try:
                settings = get_settings()
                threshold = int(settings.get("score_threshold", 6))
                score = int(matched_job.get("score", 0))
                job_id = matched_job["job_id"]
                
                pdf_path = None
                if score >= threshold:
                    # Check for tailored PDF
                    tailored_dir = Path("outputs/applications") / job_id
                    pdf_files = list(tailored_dir.glob("*.pdf"))
                    if pdf_files:
                        pdf_path = pdf_files[0]
                
                if not pdf_path and score >= threshold:
                    # Load default resume
                    default_path = PROFILE_DIR / "resume.pdf"
                    if default_path.exists():
                        pdf_path = default_path
                        
                if pdf_path and pdf_path.exists():
                    with open(pdf_path, "rb") as pdf_file:
                        response_payload["resume_base64"] = base64.b64encode(pdf_file.read()).decode('utf-8')
                        response_payload["resume_filename"] = pdf_path.name
            except Exception as e:
                print(f"[WARN] Error attaching resume: {e}")

        return response_payload
            
    except Exception as e:
        print(f"[ERROR] Sniper Answer failed: {e}")
        return {q: f"Error: {e}" for q in payload.questions}

class CompleteRequest(BaseModel):
    url: Optional[str] = None
    job_id: Optional[str] = None

@router.post("/complete")
def complete_sniper_application(payload: CompleteRequest):
    jobs = get_jobs()
    matched_job = None
    
    if payload.job_id:
        for j in jobs:
            if j.get("job_id") == payload.job_id:
                matched_job = j
                break
    elif payload.url:
        norm_incoming = normalize_url(payload.url)
        for j in jobs:
            link = j.get("apply_link", "")
            if not link:
                continue
            norm_link = normalize_url(link)
            if norm_link == norm_incoming or norm_link in norm_incoming or norm_incoming in norm_link:
                matched_job = j
                break
                
    if not matched_job:
        raise HTTPException(status_code=404, detail="Job not found in tracked jobs.")
        
    job_id = matched_job["job_id"]
    update_job(job_id, status="applied", applied_date=datetime.now().isoformat())
    
    # Clean up PDF
    tailored_dir = Path("outputs/applications") / job_id
    if tailored_dir.exists():
        for pdf_file in tailored_dir.glob("*.pdf"):
            try:
                os.remove(pdf_file)
                print(f"Deleted generated PDF: {pdf_file}")
            except Exception as e:
                print(f"Failed to delete {pdf_file}: {e}")
                
    return {"status": "success", "job_id": job_id, "message": "Application completed and cleaned up."}
