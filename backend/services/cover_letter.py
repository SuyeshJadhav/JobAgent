import tomllib
from datetime import datetime
from pathlib import Path

from backend.services.llm_client import get_llm_client, get_model_name
from backend.services.resume_tailor import safe_filename

ROOT_DIR = Path(__file__).parent.parent.parent
REFERENCES_DIR = ROOT_DIR / "references"
OUTPUT_DIR = ROOT_DIR / "outputs" / "applications"

CANDIDATE_PROFILE = REFERENCES_DIR / "candidate_profile.md"
COVER_LETTER_TEMPLATE = REFERENCES_DIR / "cover_letter_template.md"
CONTEXT_BANK = REFERENCES_DIR / "context_bank.toml"

def load_references() -> dict:
    """Load candidate_profile, cover_letter_template, and context_bank."""
    refs = {}

    if CANDIDATE_PROFILE.exists():
        refs["candidate_profile"] = CANDIDATE_PROFILE.read_text(encoding="utf-8")
    else:
        refs["candidate_profile"] = ""

    if COVER_LETTER_TEMPLATE.exists():
        refs["cover_letter_template"] = COVER_LETTER_TEMPLATE.read_text(encoding="utf-8")
    else:
        refs["cover_letter_template"] = ""

    if CONTEXT_BANK.exists():
        with open(CONTEXT_BANK, "rb") as f:
            refs["context_bank"] = tomllib.load(f)
    else:
        refs["context_bank"] = {}

    return refs


def _build_context_summary(context_bank: dict) -> str:
    """
    Build a concise text summary of experience + projects from context_bank
    so the LLM has real details to draw from.
    """
    parts = []

    for exp in context_bank.get("experience", []):
        company = exp.get("company", "Unknown")
        role = exp.get("role", "")
        parts.append(f"## {role} @ {company}")
        for key in sorted(exp.keys()):
            if key.startswith("project_"):
                proj = exp[key]
                if isinstance(proj, list):
                    for p in proj:
                        lines = [f"  {k}: {v}" for k, v in p.items()]
                        parts.append("\n".join(lines))
                elif isinstance(proj, dict):
                    lines = [f"  {k}: {v}" for k, v in proj.items()]
                    parts.append("\n".join(lines))

    for proj in context_bank.get("project", []):
        name = proj.get("name", "Unnamed")
        parts.append(f"## Project: {name}")
        lines = [f"  {k}: {v}" for k, v in proj.items() if k != "name"]
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def generate_cover_letter_content(
    jd_text: str,
    company: str,
    role: str,
    candidate_profile: str,
    cover_letter_template: str,
    context_summary: str,
) -> str:
    system = (
        "Write a cover letter for this candidate applying to this job.\n\n"
        f"CANDIDATE:\n{candidate_profile}\n\n"
        f"REAL PROJECT DETAILS (use these — never invent):\n{context_summary}\n\n"
        f"JD:\n{jd_text}\n\n"
        f"COMPANY: {company}\n"
        f"ROLE: {role}\n\n"
        f"TONE GUIDE:\n{cover_letter_template}\n\n"
        "Rules — follow ALL of these:\n"
        "- Max 250 words total\n"
        "- Exactly 3 paragraphs:\n"
        "    Para 1 — Hook: reference something specific from the JD or company\n"
        "    Para 2 — Value: pick the 2 most relevant experiences from the context above, "
        "use JD language\n"
        "    Para 3 — Close: one confident sentence CTA, no begging\n"
        "- Sound human, not corporate\n"
        '- No generic openers like "I am excited to apply"\n'
        "- Do NOT repeat resume bullets word for word — complement them\n"
        "- Reference something specific from the JD\n"
        "- Show tools in action within sentences, do not list them\n"
        '- No "passionate", "driven", or "hardworking" — show, don\'t tell\n\n'
        "Return ONLY the cover letter text. No headers, no subject lines."
    )

    client = get_llm_client()
    try:
        resp = client.chat.completions.create(
            model=get_model_name(),
            messages=[
                {"role": "system", "content": system}, 
                {"role": "user", "content": "Generate the cover letter now."}
            ],
            temperature=0.7
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating cover letter: {e}")
        return ""


def run_cover_letter(job: dict) -> dict:
    """
    Main pipeline to generate a cover letter.
    Writes output into the same target directory as resume_tailor:
    outputs/applications/{Company}-{Role}-{YYYY-MM-DD}/cover_letter.md
    """
    company = safe_filename(job.get("company", "Unknown"))
    role = safe_filename(job.get("title", "Unknown"))
    date_str = datetime.now().strftime("%Y-%m-%d")

    folder_name = f"{company}-{role}-{date_str}"
    target_dir = OUTPUT_DIR / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    refs = load_references()
    context_summary = _build_context_summary(refs["context_bank"])
    
    desc = job.get("description", "")
    if len(desc) > 8000:
        desc = desc[:8000]

    letter_text = generate_cover_letter_content(
        jd_text=desc,
        company=job.get("company", "Unknown"),
        role=job.get("title", "Unknown"),
        candidate_profile=refs["candidate_profile"],
        cover_letter_template=refs["cover_letter_template"],
        context_summary=context_summary
    )

    if not letter_text:
        return {"status": "error", "error": "Cover letter generation failed."}

    letter_path = target_dir / "cover_letter.md"
    letter_path.write_text(letter_text, encoding="utf-8")

    return {"status": "success", "output_dir": str(target_dir), "cover_letter_path": str(letter_path)}

if __name__ == "__main__":
    test_job = {
        "company": "Test Company",
        "title": "Data Scientist",
        "description": "We need someone with Python, SQL, and Machine Learning expertise.",
    }
    # It attempts a dry run to generate output files
    print(run_cover_letter(test_job))
