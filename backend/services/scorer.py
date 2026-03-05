import re
import json

from backend.services.llm_client import get_llm_client, get_model_name, get_settings


def parse_llm_json_response(content: str) -> tuple[int, str]:
    """Parse structured JSON from the LLM. Falls back to regex extraction."""
    # ── Try direct JSON parse ──
    try:
        # Strip markdown fences if present
        cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
        data = json.loads(cleaned)
        score = int(data.get("score", 0))
        reasoning = str(data.get("reasoning", ""))
        return max(0, min(10, score)), reasoning
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # ── Fallback: regex extraction ──
    score_match = re.search(r'"score"\s*:\s*(\d+)', content)
    reason_match = re.search(r'"reasoning"\s*:\s*"([^"]*)"', content, re.DOTALL)

    score = int(score_match.group(1)) if score_match else 0
    score = max(0, min(10, score))
    reason = reason_match.group(1).strip() if reason_match else content.strip()[:300]

    if not score_match:
        # Last resort: find any number
        fst = re.search(r"\b(\d{1,2})\b", content)
        score = int(fst.group(1)) if fst else 0
        score = max(0, min(10, score))

    return score, reason


def _llm_score(job: dict, profile: dict) -> tuple[int, str]:
    """
    Call LLM with a rigid deduction-based rubric.
    Temperature = 0.0, JSON mode forced.
    """
    client = get_llm_client()
    model_name = get_model_name()

    profile_summary = f"""Candidate Target Roles: {profile.get('target_roles', 'N/A')}
Candidate Key Skills: {profile.get('skills', 'N/A')}
Candidate Experience Level: {profile.get('experience_level', 'N/A')}
Candidate Preferences: {profile.get('preferences', 'N/A')}
Candidate Visa Status: Requires sponsorship (F-1 student, OPT/CPT or H1B)"""

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
              OUTPUT FORMAT
═══════════════════════════════════════════
Return ONLY valid JSON. No other text.
{
  "reasoning": "Started at 10. [deduction/bonus from Step X for ACTUAL reason]. [another deduction]. Final: [calculated number].",
  "score": [integer 0-10]
}

CRITICAL INSTRUCTION: DO NOT COPY ANY EXAMPLE TEXT.
YOU MUST READ THE ACTUAL PROVIDED JOB DESCRIPTION
AND CANDIDATE PROFILE, THEN CALCULATE THE SCORE
BASED SOLELY ON THE REAL DATA. EVERY DEDUCTION IN
YOUR REASONING MUST REFERENCE A SPECIFIC FACT FROM
THE JOB DESCRIPTION OR CANDIDATE PROFILE. IF NO
DEDUCTION APPLIES FOR A STEP, SKIP IT — DO NOT
INVENT DEDUCTIONS."""

    prompt = f"""Candidate Profile:
{profile_summary}

Job Details:
{job_summary}

Apply the deduction rubric and return JSON."""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        return parse_llm_json_response(content)
    except Exception as e:
        # If response_format isn't supported (some Ollama models), retry without it
        if "response_format" in str(e) or "json" in str(e).lower():
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.0,
                    max_tokens=300,
                )
                content = response.choices[0].message.content
                return parse_llm_json_response(content)
            except Exception as e2:
                print(f"[SCORER] LLM retry failed: {e2}")
                return 0, f"Error calling LLM: {str(e2)}"
        print(f"[SCORER] LLM request error: {e}")
        return 0, f"Error calling LLM: {str(e)}"


def score_job(job: dict, profile: dict) -> tuple[int, str]:
    """
    Score a job using local heuristics (fast pre-checks) then the LLM rubric.
    Returns (score: int, reason: str)
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
        return 2, "[PRE-CHECK] Quant firm — auto-capped at 2."

    # ── Fast pre-check: seniority in title ──
    title_lower = job.get("title", "").lower()
    SENIOR_SIGNALS = ["senior", "staff", "principal", "lead", "manager", "director", "vp ", "head of"]
    if any(sig in title_lower for sig in SENIOR_SIGNALS):
        # Exception: "Senior Intern" is fine (some companies use that)
        if "intern" not in title_lower:
            return 0, "[PRE-CHECK] Senior/Staff/Lead role — auto-rejected."

    # ── LLM scoring with deduction rubric ──
    score, reason = _llm_score(job, profile)

    # ── Post-adjustment: sponsorship bonus ──
    if job.get("is_sponsored") and get_settings().get("visa_status") == "prefer_sponsorship":
        score = min(10, score + 1)
        reason = "[SPONSORED] " + reason

    return score, reason


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
    s, r = score_job(test_job, test_profile)
    print(f"Score: {s}/10")
    print(f"Reason: {r}")

