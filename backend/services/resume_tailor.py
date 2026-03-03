import json
import re
import shutil
import subprocess
import tomllib
from datetime import datetime
from pathlib import Path

from backend.services.llm_client import get_llm_client, get_model_name, get_settings

ROOT_DIR = Path(__file__).parent.parent.parent
REFERENCES_DIR = ROOT_DIR / "references"
OUTPUT_DIR = ROOT_DIR / "outputs" / "applications"

BASE_RESUME = REFERENCES_DIR / "base_resume.tex"
CONTEXT_BANK = REFERENCES_DIR / "context_bank.toml"
CUSTOM_COMMANDS = REFERENCES_DIR / "custom-commands.tex"

def safe_filename(name: str) -> str:
    """Make string safe for filesystem."""
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()

def load_references() -> dict:
    refs = {}
    if BASE_RESUME.exists():
        refs["base_resume_tex"] = BASE_RESUME.read_text(encoding="utf-8")
    else:
        raise FileNotFoundError(f"Missing {BASE_RESUME}")
        
    if CONTEXT_BANK.exists():
        with open(CONTEXT_BANK, "rb") as f:
            refs["context_bank"] = tomllib.load(f)
    else:
        refs["context_bank"] = {}
        
    return refs

def parse_marker_sections(tex_content: str) -> dict:
    pattern = re.compile(
        r"^(?P<indent>\s*)%%\s*BEGIN\s+(?P<name>.+?)\s*%%\s*$"
        r"(?P<body>.*?)"
        r"^(?P=indent)%%\s*END\s+(?P=name)\s*%%\s*$",
        re.MULTILINE | re.DOTALL,
    )
    sections = {}
    for m in pattern.finditer(tex_content):
        name = m.group("name").strip()
        body = m.group("body")

        start_char = m.start()
        end_char = m.end()
        start_line = tex_content[:start_char].count("\n")
        end_line = tex_content[:end_char].count("\n")

        sections[name] = {
            "start": start_line,
            "end": end_line,
            "content": body.strip(),
        }
    return sections

def _get_context_for_section(section_name: str, context_bank: dict) -> str:
    fragments = []
    if section_name.upper().startswith("EXPERIENCE:"):
        company_hint = section_name.split(":", 1)[1].strip().lower()
        for exp in context_bank.get("experience", []):
            if company_hint in exp.get("company", "").lower() or company_hint in exp.get("role", "").lower():
                for key in exp:
                    if key.startswith("project_"):
                        proj = exp[key]
                        if isinstance(proj, list):
                            for p in proj:
                                fragments.append("\n".join(f"  {k}: {v}" for k, v in p.items()))
                        elif isinstance(proj, dict):
                            fragments.append("\n".join(f"  {k}: {v}" for k, v in proj.items()))

    if section_name.upper().startswith("PROJECTS:"):
        project_hint = section_name.split(":", 1)[1].strip().lower()
        for proj in context_bank.get("project", []):
            if project_hint in proj.get("name", "").lower():
                fragments.append("\n".join(f"  {k}: {v}" for k, v in proj.items()))

    return "\n---\n".join(fragments) if fragments else ""

def _get_voice_samples(context_bank: dict) -> str:
    samples = []
    for vs in context_bank.get("voice_samples", []):
        s = vs.get("samples", [])
        if isinstance(s, list):
            samples.extend(s)
    return "\n".join(f"- {s}" for s in samples) if samples else ""

def extract_jd_keywords(jd_text: str) -> dict:
    system = (
        "You are a JD analysis engine. Extract structured keywords. Return ONLY valid JSON with keys: "
        '"required_skills", "action_verbs", "seniority_signals", "domain_focus".'
    )
    client = get_llm_client()
    try:
        resp = client.chat.completions.create(
            model=get_model_name(),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": jd_text}],
            temperature=0.3
        )
        content = resp.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        return json.loads(content)
    except Exception:
        return {"required_skills": [], "action_verbs": [], "seniority_signals": [], "domain_focus": []}

def rewrite_bullets(section_name: str, current_text: str, keywords: dict, context_bank: dict) -> str:
    context_notes = _get_context_for_section(section_name, context_bank)
    voice = _get_voice_samples(context_bank)
    kw_str = json.dumps(keywords, indent=2)

    system = (
        "You are editing LaTeX resume bullet points for a specific job.\n\n"
        f"JD KEYWORDS:\n{kw_str}\n\n"
        "Rules:\n"
        "- Rewrite bullets to use JD verbs and keywords natively\n"
        "- Never add tools/experience not in original\n"
        "- Never modify LaTeX commands, just the text\n"
        "- Return ONLY the rewritten bullet lines with LaTeX commands kept exactly\n"
        "- Add metrics where provided\n"
    )

    if context_notes:
        system += f"\nREAL CONTEXT (use these exact details):\n{context_notes}\n"
    if voice:
        system += f"\nCANDIDATE VOICE:\n{voice}\n"

    user_msg = (
        f"SECTION: {section_name}\n\n"
        f"CURRENT BULLETS:\n{current_text}\n\n"
        "Rewrite bullets safely."
    )

    client = get_llm_client()
    resp = client.chat.completions.create(
        model=get_model_name(),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        temperature=0.7
    )
    return resp.choices[0].message.content.strip()

def assemble_tailored_tex(base_tex: str, sections: dict, rewritten: dict) -> str:
    lines = base_tex.split("\n")
    result_lines = lines.copy()

    for section_name in sorted(rewritten.keys(), key=lambda s: sections[s]["start"], reverse=True):
        sec = sections[section_name]
        begin_line = sec["start"]
        end_line = sec["end"]
        new_content = rewritten[section_name]
        result_lines[begin_line + 1:end_line] = [new_content]

    return "\n".join(result_lines)

def run_tailor(job: dict) -> dict:
    """
    Main pipeline to tailor a resume.
    1. Creates output directory
    2. Modifies tex based on job description
    3. Runs pdflatex
    4. Saves meta JSON
    """
    settings = get_settings()
    candidate_name = settings.get("candidate_name", "Suyesh Jadhav")
    safe_name = safe_filename(candidate_name)

    company = safe_filename(job.get("company", "Unknown"))
    role = safe_filename(job.get("title", "Unknown"))
    date_str = datetime.now().strftime("%Y-%m-%d")

    folder_name = f"{company}-{role}-{date_str}"
    target_dir = OUTPUT_DIR / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    # Export job details json
    job["tailored_at"] = datetime.now().isoformat()
    with open(target_dir / "job_details.json", "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)

    refs = load_references()
    sections = parse_marker_sections(refs["base_resume_tex"])

    # 1. Keywords
    desc = job.get("description", "")
    if len(desc) > 8000:
        desc = desc[:8000]
    
    keywords = extract_jd_keywords(desc)

    # 2. Rewrite
    rewritten = {}
    for section_name, sec_data in sections.items():
        if section_name.upper() in ("SUMMARY", "SKILLS") or any(k.lower() in section_name.lower() for k in keywords.get("domain_focus", [])):
            print(f"Tailoring section: {section_name}")
            new_text = rewrite_bullets(section_name, sec_data["content"], keywords, refs["context_bank"])
            rewritten[section_name] = new_text

    # 3. Assemble and save tex
    tailored_tex = assemble_tailored_tex(refs["base_resume_tex"], sections, rewritten)
    tex_path = target_dir / "resume.tex"
    tex_path.write_text(tailored_tex, encoding="utf-8")

    # Move dependencies
    if CUSTOM_COMMANDS.exists():
        shutil.copy(CUSTOM_COMMANDS, target_dir / "custom-commands.tex")

    # Compile PDF
    pdf_path = target_dir / f"{safe_name}.pdf"
    
    try:
        pid = subprocess.run(
            [
                "pdflatex",
                f"-jobname={safe_name}",
                "-interaction=nonstopmode",
                "-output-directory", str(target_dir),
                str(tex_path)
            ],
            capture_output=True, text=True, timeout=60
        )
        if pdf_path.exists():
            return {"status": "success", "output_dir": str(target_dir), "pdf_path": str(pdf_path)}
        else:
            return {"status": "error", "error": f"PDF compilation failed: {pid.stdout[-500:]}"}
    except FileNotFoundError:
        return {"status": "error", "error": "pdflatex is not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

if __name__ == "__main__":
    job_mock = {
        "job_id": "test1234",
        "company": "Test Company",
        "title": "Data Scientist",
        "description": "We need Python, SQL, and Machine Learning expertise.",
        "score": 9,
        "reason": "Good match",
        "apply_link": "https://example.com"
    }
    
    # We will test simply if the files parse ok!
    print(safe_filename("Suyesh Jadhav"))
