import re
import json

from backend.services.llm_client import get_llm_client, get_model_name, get_settings


def parse_llm_json_response(content: str) -> dict:
    """
    Parses structured JSON from the LLM response.
    Includes robust fallback logic using regex if the JSON is malformed or
    wrapped in markdown fences.

    Args:
        content (str): Raw string content from the LLM.

    Returns:
        dict: {score: int, reasoning: str,
            company: str, title: str, strategy: str}
    """
    result = {"score": 0, "reasoning": "", "company": "",
              "title": "", "strategy": "skills_only"}

    # ── Try direct JSON parse ──
    try:
        # Strip markdown fences if present
        cleaned = re.sub(r"^```(?:json)?\s*", "",
                         content.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
        data = json.loads(cleaned)
        result["score"] = max(0, min(100, int(data.get("score", 0))))
        result["reasoning"] = str(data.get("reasoning", ""))
        result["company"] = str(data.get("company", "")).strip()
        result["title"] = str(data.get("title", "")).strip()
        result["strategy"] = str(data.get("strategy", "skills_only"))
        return result
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # ── Fallback: regex extraction ──
    score_match = re.search(r'"score"\s*:\s*(\d+)', content)
    reason_match = re.search(
        r'"reasoning"\s*:\s*"([^"]*)"', content, re.DOTALL)
    company_match = re.search(r'"company"\s*:\s*"([^"]*)"', content)
    title_match = re.search(r'"title"\s*:\s*"([^"]*)"', content)

    if score_match:
        result["score"] = max(0, min(100, int(score_match.group(1))))
    else:
        # Last resort: find any number
        fst = re.search(r"\b(\d{1,3})\b", content)
        result["score"] = max(0, min(100, int(fst.group(1)))) if fst else 0

    result["reasoning"] = reason_match.group(
        1).strip() if reason_match else content.strip()[:300]
    result["company"] = company_match.group(1).strip() if company_match else ""
    result["title"] = title_match.group(1).strip() if title_match else ""

    return result


def _format_profile_summary(profile: dict) -> str:
    """
    Formats the candidate's profile data into a concise string for the LLM prompt.

    Args:
        profile (dict): Parsed candidate profile data.

    Returns:
        str: Formatted profile summary.
    """
    return f"""Candidate Target Roles: {profile.get('target_roles', 'N/A')}
Candidate Key Skills: {profile.get('skills', 'N/A')}
Candidate Experience Level: {profile.get('experience_level', 'N/A')}
Candidate Preferences: {profile.get('preferences', 'N/A')}
Candidate Visa Status: Requires sponsorship (F-1 student, OPT/CPT or H1B)"""


def _build_scoring_prompt(job: dict, profile: dict) -> tuple[str, str]:
    """
    Constructs the system and user prompts for the LLM scoring engine.
    Ensures the 'BASE-10 DEDUCTION RUBRIC' is clearly communicated.

    Args:
        job (dict): Job record.
        profile (dict): Candidate profile.

    Returns:
        tuple[str, str]: (system_prompt, user_prompt)
    """
    profile_summary = _format_profile_summary(profile)
    jd_text = job.get('description', '')
    if len(jd_text) > 10000:
        jd_text = jd_text[:10000]

    job_summary = f"""Company: {job.get('company', 'Unknown')}
Job Title: {job.get('title', 'Unknown')}
Description: {jd_text}"""

    system = r"""You are a deterministic job-fit scoring engine.
You MUST follow the BASE-10 DEDUCTION RUBRIC exactly.
Do NOT guess. Calculate the score mechanically.

═══════════════════════════════════════════
         BASE-10 DEDUCTION RUBRIC
═══════════════════════════════════════════

START at 10/10. Apply deductions in order:

STEP 1 — AUTO-REJECT (score becomes 0 immediately):
  • Job explicitly requires US Citizenship or
    Security Clearance → SCORE 0.
  • Job is Senior / Staff / Principal / Lead /
    Manager / Director level → SCORE 0.
  If either auto-reject fires, stop here.

STEP 2 — EXPERIENCE GAP:
  • Job requires 3-4 years experience →  -2
  • Job requires 5+ years experience  →  -3
  • Job is explicitly intern/new-grad  →  -0

STEP 3 — CORE TECH STACK MISMATCH:
  For each REQUIRED technology the candidate
  is MISSING (not just "nice to have"):
  • Missing 1 core tech → -1
  • Missing 2 core techs → -2
  • Missing 3+ core techs → -3 (cap)
  Only count technologies the JD marks as
  "required" or "must-have", not "preferred".

STEP 4 — DOMAIN PENALTY:
  • Quant trading / hedge fund → -4
  • Legal tech → -5
  • Non-tech company (retail, food, pharma
    with no software team mentioned) → -3
  • Finance/banking (unless explicitly
    software engineering team) → -3
  • Pure software/AI/ML company → -0

STEP 5 — ROLE RELEVANCE BONUS (add back):
  • Role title matches candidate's target
    roles exactly → +1
  • Role involves AI/ML/LLM work → +1
  (Max total score is still capped at 10)

FINAL SCORE = max(0, min(10, result))

═══════════════════════════════════════════
             TAILORING STRATEGY
═══════════════════════════════════════════
Based on the final score and JD requirements, select a strategy:
• "skills_only": Output this if the candidate is a strong match (Score >= 7)
  and primarily needs keyword alignment in the Skills section without
  altering core project achievements.
• "full_rewrite": Output this ONLY if the job requires deep surgical weaving
  of keywords into the Experience/Projects bullets to be competitive.

═══════════════════════════════════════════
               OUTPUT FORMAT
═══════════════════════════════════════════
Return ONLY valid JSON. No other text.
{
  "company": "<real company name from the JD>",
  "title": "<exact job title from the JD>",
  "reasoning": "...",
  "score": [integer 0-10],
  "strategy": "skills_only" | "full_rewrite"
}

IMPORTANT: Extract the REAL company name and
exact job title from the JD text, NOT from the
metadata fields provided. The metadata may
contain incorrect website artifacts.

CRITICAL INSTRUCTION: EVERY DEDUCTION IN
YOUR REASONING MUST REFERENCE A SPECIFIC FACT FROM
THE JOB DESCRIPTION OR CANDIDATE PROFILE."""

    user_msg = f"""Candidate Profile:
{profile_summary}

Job Details:
{job_summary}

Apply the deduction rubric and return JSON."""

    return system, user_msg


def _execute_llm_scoring(system: str, user_msg: str) -> dict:
    """
    Executes the LLM API call with robust error handling and model-specific
    compatibility logic (e.g., support for JSON mode).

    Args:
        system (str): System prompt.
        user_msg (str): User prompt.

    Returns:
        dict: {score, reasoning, company, title, strategy}
    """
    client = get_llm_client()
    model_name = get_model_name()

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.0,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        return parse_llm_json_response(response.choices[0].message.content)
    except Exception as e:
        # Fallback for models not supporting response_format="json_object"
        if "response_format" in str(e).lower() or "json" in str(e).lower():
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg}
                    ],
                    temperature=0.0,
                    max_tokens=400,
                )
                return parse_llm_json_response(response.choices[0].message.content)
            except Exception as e2:
                return {"score": 0, "reasoning": f"Error calling LLM: {str(e2)}", "company": "", "title": "", "strategy": "skills_only"}
        return {"score": 0, "reasoning": f"Error calling LLM: {str(e)}", "company": "", "title": "", "strategy": "skills_only"}


def _llm_score(job: dict, profile: dict) -> dict:
    """
    Internal wrapper to orchestrate the prompt building and LLM execution.

    Args:
        job (dict): Job record.
        profile (dict): Candidate profile.

    Returns:
        dict: {score, reasoning, company, title, strategy}
    """
    system, user_msg = _build_scoring_prompt(job, profile)
    return _execute_llm_scoring(system, user_msg)


def score_job(job: dict, profile: dict) -> dict:
    """
    Primary API to score a job for a candidate.
    Combines fast local heuristic pre-checks (for known auto-rejects/caps)
    with a sophisticated LLM deduction rubric.

    Args:
        job (dict): Job record.
        profile (dict): Candidate profile.

    Returns:
        dict: {score: int, reasoning: str,
            company: str, title: str, strategy: str}
    """
    # ── Fast pre-check: known quant firms ──
    QUANT_FIRMS = {
        "two sigma", "de shaw", "jane street",
        "citadel", "tower research", "sig",
        "virtu", "akuna", "optiver", "imc",
        "hudson river trading", "jump trading",
        "renaissance", "millennium", "point72"
    }

    company_lower = job.get("company", "").lower()
    if any(firm in company_lower for firm in QUANT_FIRMS):
        return {
            "score": 20,
            "reasoning": "[PRE-CHECK] Quant firm — auto-capped at 20.",
            "company": "",
            "title": "",
            "strategy": "skills_only",
        }

    # ── Fast pre-check: seniority in title ──
    title_lower = job.get("title", "").lower()
    SENIOR_SIGNALS = ["senior", "staff", "principal",
                      "lead", "manager", "director", "vp ", "head of"]
    if any(sig in title_lower for sig in SENIOR_SIGNALS):
        # Exception: "Senior Intern" is fine (some companies use that)
        if "intern" not in title_lower:
            return {"score": 0, "reasoning": "[PRE-CHECK] Senior/Staff/Lead role — auto-rejected.", "company": "", "title": "", "strategy": "skills_only"}

    # ── LLM scoring with deduction rubric ──
    result = _llm_score(job, profile)

    # ── Post-adjustment: sponsorship bonus ──
    if job.get("is_sponsored") and get_settings().get("visa_status") == "prefer_sponsorship":
        result["score"] = min(100, result["score"] + 10)
        result["reasoning"] = "[SPONSORED] " + result["reasoning"]

    return result


# ── Local testing ──
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
    result = score_job(test_job, test_profile)
    print(f"Score: {result['score']}/100")
    print(f"Reason: {result['reasoning']}")
    print(f"Company: {result['company']}")
    print(f"Title: {result['title']}")
