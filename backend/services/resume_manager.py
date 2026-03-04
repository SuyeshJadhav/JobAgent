import base64
import os
import re
from pathlib import Path
from datetime import datetime
from backend.services.llm_client import get_llm_client, get_model_name, get_settings
from backend.services.resume_tailor import run_tailor

ROOT_DIR = Path(__file__).parent.parent.parent
DEFAULT_RESUME_PATH = ROOT_DIR / "references" / "base_resume.pdf"
TEMP_DIR = ROOT_DIR / "backend" / "temp_resumes"

def evaluate_and_fetch_resume(job_description: str, default_resume_path: str = None) -> dict:
    """
    Scores the default resume against the job description.
    If score >= 80, returns the default resume.
    If score < 80, generates a tailored resume.
    """
    if default_resume_path is None:
        default_resume_path = str(DEFAULT_RESUME_PATH)
    
    # 1. Score the resume match (0-100)
    score = score_resume(job_description)
    print(f"Resume Alignment Score: {score}/100")

    result = {
        "score": score,
        "is_generated": False,
        "base64_file": "",
        "filename": "Resume_Suyesh_Jadhav.pdf",
        "generated_resume_path": ""
    }

    if score >= 80:
        # Return default resume
        with open(default_resume_path, "rb") as f:
            result["base64_file"] = base64.b64encode(f.read()).decode("utf-8")
    else:
        # Trigger tailoring
        print("Score below 80, triggering resume tailoring...")
        job_mock = {
            "title": "Target Role", # We might want to pass more details here
            "company": "Job Site",
            "description": job_description
        }
        
        tailor_result = run_tailor(job_mock)
        
        if tailor_result.get("status") in ("success", "warning"):
            generated_pdf = Path(tailor_result["pdf_path"])
            result["is_generated"] = True
            result["generated_resume_path"] = str(generated_pdf)
            result["filename"] = f"Resume_Suyesh_Jadhav_Tailored.pdf"
            
            with open(generated_pdf, "rb") as f:
                result["base64_file"] = base64.b64encode(f.read()).decode("utf-8")
            
            # Note: We keep the file for now, cleanup happens in Task 3
        else:
            print(f"Tailoring failed: {tailor_result.get('error')}. Falling back to default.")
            with open(default_resume_path, "rb") as f:
                result["base64_file"] = base64.b64encode(f.read()).decode("utf-8")

    return result

def score_resume(jd_text: str) -> int:
    """Uses the LLM to score the alignment between the JD and the candidate profile."""
    # Since we don't have a plain text version of the PDF easily here without more overhead,
    # we'll use the candidate profile as a proxy for the 'default resume' content.
    profile_path = ROOT_DIR / "references" / "candidate_profile.md"
    profile_content = profile_path.read_text(encoding="utf-8") if profile_path.exists() else "Candidate Profile not found."

    system = """You are an expert recruiter. 
Score the alignment between the candidate's profile and the job description on a scale of 0-100.
Consider skills, experience, and project relevance.
Return ONLY the numerical score (e.g., 85)."""

    user_msg = f"JOB DESCRIPTION:\n{jd_text}\n\nCANDIDATE PROFILE:\n{profile_content}"
    
    client = get_llm_client()
    try:
        resp = client.chat.completions.create(
            model=get_model_name(),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
            temperature=0.0,
            max_tokens=10
        )
        content = resp.choices[0].message.content.strip()
        score_match = re.search(r"(\d+)", content)
        if score_match:
            return int(score_match.group(1))
        return 75 # Default fallback
    except Exception as e:
        print(f"Error scoring resume: {e}")
        return 75
