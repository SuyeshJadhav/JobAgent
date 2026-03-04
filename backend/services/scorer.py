import re

from backend.services.llm_client import get_llm_client, get_model_name, get_settings

AUTO_SHORTLIST = 0.35   # was 0.45
AUTO_SKIP = 0.25        # was 0.20

def parse_llm_response(content: str) -> tuple[int, str]:
    """Parse the LLM response to ensure we always get a valid int score and string reason."""
    try:
        # Expected format from LLM:
        # Score: 8
        # Reason: The job aligns well...
        
        score_match = re.search(r"Score:\s*(\d+)", content, re.IGNORECASE)
        reason_match = re.search(r"Reason:\s*(.*)", content, re.IGNORECASE | re.DOTALL)
        
        score_num = int(score_match.group(1)) if score_match else 0
        # Clamp score between 1 and 10
        score = max(1, min(10, score_num))
        
        reason = reason_match.group(1).strip() if reason_match else content.strip()
        
        if not score_match:
            # Fallback if no specific format exists
            # We will just look for the first number it spits out
            fst_num = re.search(r"\b([1-9]|10)\b", content)
            if fst_num:
                score = int(fst_num.group(1))
            else:
                score = 1
                
        return score, reason
    except Exception as e:
        print(f"Error parsing score from LLM response: {e}")
        return 1, "Failed to parse reasoning from LLM."


def _llm_score(job: dict, profile: dict) -> tuple[int, str]:
    """Call LLM to score the job match."""
    client = get_llm_client()
    model_name = get_model_name()
    
    # Combined profile info
    profile_summary = f"""
Candidate Target Roles: {profile.get('target_roles', 'Not specified')}
Candidate Key Skills: {profile.get('skills', 'Not specified')}
Candidate Experience Level: {profile.get('experience_level', 'Not specified')}
Candidate Preferences: {profile.get('preferences', 'Not specified')}
"""

    job_description_snippet = job.get('description', '')
    if len(job_description_snippet) > 10000:
        job_description_snippet = job_description_snippet[:10000]

    job_summary = f"""
Company: {job.get('company')}
Job Title: {job.get('title')}
Description: {job_description_snippet}
"""

    system = """You are a resume-job fit evaluator.
Score this internship/new grad job from 1-10 for
this specific candidate.

SCORING RULES:

STEP 1 — Company domain check (apply FIRST):
  Quant trading / hedge fund (Two Sigma, DE Shaw,
  Jane Street, Citadel, Tower Research, SIG):
    → max score 4, even if they use ML/Python
  Legal tech company:
    → max score 3
  Finance/banking (Goldman, JPMorgan, etc):
    → max score 4 unless explicitly software team
  Non-tech company (retail, food, healthcare):
    → max score 5
  Pure software / AI / ML company:
    → score normally, no cap

STEP 2 — Role level check:
  Requires 3+ years experience → score 1
  Requires specific hardware/embedded skills
  candidate doesn't have → score 2
  Clearly intern/new grad level → continue

STEP 3 — Skills match check:
  Strong match (LLM/RAG/Python/FastAPI/React) → 8-10
  Partial match (some overlap) → 5-7
  Weak match (different domain) → 3-4
  No match → 1-2

SCORING SCALE:
  9-10: Perfect fit — AI/ML/SWE intern at tech company,
        strong skills overlap
  7-8:  Good fit — SWE intern, decent skills overlap
  5-6:  Borderline — some overlap, worth applying
  3-4:  Poor fit — wrong domain or weak skills match
  1-2:  Skip — quant/finance/wrong level/no match

Return EXACTLY in this format (no other text):
Score: X
Reason: one sentence explanation"""

    prompt = f"""
Candidate Profile:
{profile_summary}

Job Details:
{job_summary}
"""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=200
        )
        content = response.choices[0].message.content
        return parse_llm_response(content)
    except Exception as e:
        print(f"LLM request error: {e}")
        return 0, f"Error calling LLM: {str(e)}"


def score_job(job: dict, profile: dict) -> tuple[int, str]:
    """
    Score a job using local heuristics then an LLM call.
    Returns (score: int, reason: str)
    """
    # Placeholder for keyword match stage (if any)
    # (Actually we'll just implement the pre-check here as requested)

    QUANT_FIRMS = {
        "two sigma", "de shaw", "jane street",
        "citadel", "tower research", "sig",
        "virtu", "akuna", "optiver", "imc",
        "hudson river trading", "jump trading",
        "renaissance", "millenium", "point72"
    }
    
    company_lower = job.get("company","").lower()
    
    if any(firm in company_lower 
           for firm in QUANT_FIRMS):
        return 3, "QUANT_FIRM: Score capped at 3"

    score, reason = _llm_score(job, profile)

    if job.get("is_sponsored") and get_settings().get("visa_status") == "prefer_sponsorship":
        score = min(10, score + 2)
        reason = "[SPONSORED] " + reason
        
    return score, reason

# A quick helper block for local testing
if __name__ == "__main__":
    test_job = {
        "title": "Machine Learning Intern",
        "company": "OpenAI",
        "description": "We are looking for an ML Intern to work on large language models. Require PyTorch and Python experience. Summer 2026."
    }
    test_profile = {
         "target_roles": "ML Intern, AI Intern, SWE Intern",
         "skills": "Python, PyTorch, LangChain, Kubernetes",
         "experience_level": "Masters student, looking for Summer Internship",
         "preferences": "AI/ML focus, remote or relocated"
    }
    score, reason = score_job(test_job, test_profile)
    print(f"Score: {score}/10")
    print(f"Reason: {reason}")
