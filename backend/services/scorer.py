import json
import re
from backend.services.llm_client import get_llm_client, get_model_name, get_settings

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


def score_job(job: dict, profile: dict) -> tuple[int, str]:
    """
    Score a job using an LLM call based on the job details and Candidate's profile.
    Returns (score: int, reason: str)
    """
    client = get_llm_client()
    model_name = get_model_name()
    
    # We combine relevant info from the profile into a readable format for the LLM
    profile_summary = f"""
Candidate Target Roles: {profile.get('target_roles', 'Not specified')}
Candidate Key Skills: {profile.get('skills', 'Not specified')}
Candidate Experience Level: {profile.get('experience_level', 'Not specified')}
Candidate Preferences: {profile.get('preferences', 'Not specified')}
"""

    job_description_snippet = job.get('description', '')
    # Truncate description if extremely long so we don't blow token counts
    if len(job_description_snippet) > 10000:
        job_description_snippet = job_description_snippet[:10000]

    job_summary = f"""
Company: {job.get('company')}
Job Title: {job.get('title')}
Description Limit snippet: {job_description_snippet}
"""

    prompt = f"""
You are an expert technical recruiter AI evaluating how well a job posting matches a candidate's profile.
Please score the job fit from 1 to 10 based on these criteria:
* Role title match: Is this the right type of role?
* Seniority match: Does this match their expected level (e.g., intern/new grad)?
* Skills overlap: How many required skills from the Job Description does the candidate possess?
* Domain match: Is it aligned with AI/ML/SWE?
* Red flags: Are there major red flags (e.g. requires 5+ years of experience for an intern role, completely unrelated domain)?

Score strictly (1 = terrible fit or major red flag, 10 = perfect fit). 
If it is obviously a senior level job but the candidate is entry level, give a very low score (e.g., 1-3).
If the domain has NO correlation to the candidate's target roles, give a very low score.

Here is the Candidate Profile:
{profile_summary}

Here is the Job:
{job_summary}

You MUST reply in exactly the following format:
Score: [number from 1 to 10]
Reason: [A 1-2 sentence explanation of why you gave this score]
"""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a precise and critical job-matching AI."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=200
        )
        content = response.choices[0].message.content
        return parse_llm_response(content)
    except Exception as e:
        print(f"LLM request error during job scoring: {e}")
        return 0, f"Error calling LLM: {str(e)}"

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
