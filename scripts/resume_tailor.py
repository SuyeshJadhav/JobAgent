"""
Resume Tailor — rewrites LaTeX resume bullets to mirror a JD's keywords.

Usage:
    python scripts/resume_tailor.py --job_id <id>
    python scripts/resume_tailor.py --jd-text "paste JD here" --company Google --role "AI Engineer"

Pipeline import:
    from scripts.resume_tailor import run
    run(job_id="abc123")
"""

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from utils import check_ollama, llm_call, log, read_score_threshold, safe_filename

# ── Paths ────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
REFERENCES = ROOT_DIR / "references"
DB_PATH = ROOT_DIR / "scout_jobs.db"
OUTPUT_DIR = ROOT_DIR / "outputs" / "resumes"

BASE_RESUME = REFERENCES / "base_resume.tex"
CONTEXT_BANK = REFERENCES / "context_bank.toml"
CANDIDATE_PROFILE = REFERENCES / "candidate_profile.md"
CUSTOM_COMMANDS = REFERENCES / "custom-commands.tex"


# ── Reference loading ────────────────────────────────────────
def load_references() -> dict:
    """Load all reference files. Returns dict with raw content."""
    refs: dict = {}

    if not BASE_RESUME.exists():
        sys.exit(f"ERROR: base_resume.tex not found at {BASE_RESUME}")
    refs["base_resume_tex"] = BASE_RESUME.read_text(encoding="utf-8")

    if CONTEXT_BANK.exists():
        with open(CONTEXT_BANK, "rb") as f:
            refs["context_bank"] = tomllib.load(f)
    else:
        log("WARNING: context_bank.toml not found — bullets will lack context")
        refs["context_bank"] = {}

    if CANDIDATE_PROFILE.exists():
        refs["candidate_profile"] = CANDIDATE_PROFILE.read_text(encoding="utf-8")
    else:
        log("WARNING: candidate_profile.md not found")
        refs["candidate_profile"] = ""

    return refs


# ── Database ─────────────────────────────────────────────────
def get_jd_from_db(job_id: str) -> dict | None:
    """
    Query scout_jobs.db for a job by job_id (TEXT primary key).
    Returns dict with title, company, description, score, etc.
    Returns None if not found or DB doesn't exist.
    """
    if not DB_PATH.exists():
        log(f"WARNING: Database not found at {DB_PATH}")
        return None

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_db(job_id: str, resume_path: str) -> None:
    """Set resume_path, status='resume_ready', and last_updated in DB."""
    if not DB_PATH.exists():
        log("WARNING: Database not found — skipping DB update")
        return

    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """UPDATE jobs
               SET resume_path = ?, status = 'resume_ready', last_updated = ?
               WHERE job_id = ?""",
            (resume_path, datetime.now(timezone.utc).isoformat(), job_id),
        )
        conn.commit()
        log(f"DB updated: job_id={job_id} → status=resume_ready")
    finally:
        conn.close()


# ── Marker parser ────────────────────────────────────────────
def parse_marker_sections(tex_content: str) -> dict:
    """
    Extract all %% BEGIN <name> %% ... %% END <name> %% blocks.

    Returns:
        {
            "SUMMARY": {"start": <line_idx>, "end": <line_idx>, "content": "..."},
            "EXPERIENCE: KJSCE Software Development Cell": { ... },
            ...
        }
    """
    pattern = re.compile(
        r"^(?P<indent>\s*)%%\s*BEGIN\s+(?P<name>.+?)\s*%%\s*$"
        r"(?P<body>.*?)"
        r"^(?P=indent)%%\s*END\s+(?P=name)\s*%%\s*$",
        re.MULTILINE | re.DOTALL,
    )

    sections: dict = {}
    tex_content.split("\n")

    for m in pattern.finditer(tex_content):
        name = m.group("name").strip()
        body = m.group("body")

        # Compute line numbers (0-indexed in the list, 1-indexed for display)
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


# ── Section relevance (replaces map_keywords_to_sections) ────
def is_section_relevant(section_name: str, keywords: dict) -> bool:
    """
    Simple heuristic: a section is relevant if any domain_focus keyword
    appears in the section name.  SUMMARY and SKILLS are always rewritten.
    """
    section_lower = section_name.lower()

    # Always rewrite summary and skills
    if section_lower in ("summary", "skills", "header"):
        return True

    return any(k.lower() in section_lower for k in keywords.get("domain_focus", []))


# ── LLM helpers ──────────────────────────────────────────────
# llm_call() is provided by utils


def extract_jd_keywords(jd_text: str, model: str) -> dict:
    """
    LLM extracts structured keywords from a JD.
    Returns JSON with: required_skills, action_verbs, seniority_signals, domain_focus.
    """
    system = (
        "You are a JD analysis engine. Given a job description, extract structured "
        "keywords. Return ONLY valid JSON with these exact keys:\n"
        '  "required_skills": list of tools, languages, frameworks mentioned\n'
        '  "action_verbs": list of role-specific verbs (deploy, fine-tune, design, scale, etc.)\n'
        '  "seniority_signals": list of seniority/level indicators\n'
        '  "domain_focus": list of domain/area keywords (e.g. AI, backend, ML, NLP, data, full-stack)\n'
        "Do NOT wrap in markdown. Return raw JSON only."
    )

    result = llm_call(
        [{"role": "system", "content": system}, {"role": "user", "content": jd_text}],
        model=model,
        temperature=0.3,
    )

    # Strip markdown fences if LLM wraps them anyway
    result = re.sub(r"^```(?:json)?\s*", "", result)
    result = re.sub(r"\s*```$", "", result)

    try:
        return json.loads(result)
    except json.JSONDecodeError:
        log("WARNING: LLM returned non-JSON for keywords — using empty dict")
        return {
            "required_skills": [],
            "action_verbs": [],
            "seniority_signals": [],
            "domain_focus": [],
        }


def _get_context_for_section(section_name: str, context_bank: dict) -> str:
    """
    Pull relevant context_bank entries for a given section name.
    Matches experience entries by company name, project entries by project name.
    """
    fragments: list[str] = []

    # Match EXPERIENCE sections
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

    # Match PROJECT sections
    if section_name.upper().startswith("PROJECTS:"):
        project_hint = section_name.split(":", 1)[1].strip().lower()
        for proj in context_bank.get("project", []):
            if project_hint in proj.get("name", "").lower():
                fragments.append("\n".join(f"  {k}: {v}" for k, v in proj.items()))

    return "\n---\n".join(fragments) if fragments else ""


def _get_voice_samples(context_bank: dict) -> str:
    """Extract voice samples from context_bank for tone matching."""
    samples = []
    for vs in context_bank.get("voice_samples", []):
        s = vs.get("samples", [])
        if isinstance(s, list):
            samples.extend(s)
    return "\n".join(f"- {s}" for s in samples) if samples else ""


def rewrite_bullets(
    section_name: str,
    current_text: str,
    keywords: dict,
    context_bank: dict,
    model: str,
) -> str:
    """
    LLM rewrites bullet text for one section.
    Follows the prompt pattern from SKILL.md exactly.
    """
    context_notes = _get_context_for_section(section_name, context_bank)
    voice = _get_voice_samples(context_bank)

    kw_str = json.dumps(keywords, indent=2)

    system = (
        "You are editing LaTeX resume bullet points for a specific job.\n\n"
        f"JD KEYWORDS:\n{kw_str}\n\n"
        "Rules:\n"
        "- Rewrite bullets to use JD verbs and keywords where they naturally fit\n"
        "- Keep each bullet under 2 lines\n"
        "- Never add tools or experience not in the original\n"
        "- Never modify LaTeX commands (\\resumeItem, \\imp, \\href, etc.) — only edit the text content\n"
        "- Return ONLY the rewritten bullet lines, preserving all LaTeX commands exactly\n"
        "- Follow the human-sounding bullet formula: ACTION VERB + WHAT + HOW/TOOL + RESULT/SCALE\n"
        "- Vary verb and sentence structure — not every bullet should start with the same word\n"
        '- Include before/after metrics where available ("from X to Y")\n'
        "- Mention specific tool choices and why when relevant\n"
        "- Make bullets sound like they could NOT be copy-pasted onto someone else's resume\n"
    )

    if context_notes:
        system += f"\nREAL CONTEXT (use these real numbers and details — never invent):\n{context_notes}\n"

    if voice:
        system += f"\nCANDIDATE VOICE SAMPLES (match this phrasing rhythm):\n{voice}\n"

    user_msg = (
        f"SECTION: {section_name}\n\n"
        f"CURRENT BULLETS (preserve LaTeX commands exactly):\n{current_text}\n\n"
        "Rewrite the above bullets. Return ONLY the rewritten lines."
    )

    return llm_call(
        [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        model=model,
        temperature=0.7,
    )


# ── Assembler ────────────────────────────────────────────────
def assemble_tailored_tex(base_tex: str, sections: dict, rewritten: dict[str, str]) -> str:
    """
    Replace marker-block content in base_tex with rewritten text.
    Only sections present in `rewritten` are replaced.
    """
    lines = base_tex.split("\n")
    result_lines = lines.copy()

    # Work backwards so line indices stay valid
    for section_name in sorted(
        rewritten.keys(),
        key=lambda s: sections[s]["start"],
        reverse=True,
    ):
        sec = sections[section_name]
        begin_line = sec["start"]  # line with %% BEGIN ... %%
        end_line = sec["end"]  # line with %% END ... %%

        # Replace everything between BEGIN and END (exclusive)
        new_content = rewritten[section_name]
        result_lines[begin_line + 1:end_line] = [new_content]

    return "\n".join(result_lines)


# ── Compiler ─────────────────────────────────────────────────
def compile_pdf(tex_path: Path) -> Path | None:
    """Run pdflatex and return the PDF path, or None on failure."""
    log(f"Compiling: {tex_path.name}")

    try:
        result = subprocess.run(
            [
                "pdflatex",
                "-interaction=nonstopmode",
                "-output-directory",
                str(tex_path.parent),
                str(tex_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        log("ERROR: pdflatex not found — install texlive or set PATH")
        return None
    except subprocess.TimeoutExpired:
        log("ERROR: pdflatex timed out after 60s")
        return None

    pdf_path = tex_path.with_suffix(".pdf")
    if pdf_path.exists() and pdf_path.stat().st_size > 0:
        log(f"PDF OK: {pdf_path.name} ({pdf_path.stat().st_size:,} bytes)")
        return pdf_path

    log(f"ERROR: PDF compilation failed.\n{result.stdout[-500:]}")
    return None


def _validate_job_for_tailoring(
    job_id: str | None, jd_text: str | None, company: str | None, role: str | None, refs: dict
) -> tuple[str, str, str] | None:
    """Validate DB job/scores and return (jd_text, company, role) if valid, else None."""
    job_row = None
    if job_id and not jd_text:
        log(f"Looking up job_id={job_id} in database...")
        job_row = get_jd_from_db(job_id)
        if job_row:
            jd_text = job_row.get("description", "")
            company = company or job_row.get("company", "Unknown")
            role = role or job_row.get("title", "Unknown")
            score = job_row.get("score")
            threshold = read_score_threshold(refs["candidate_profile"])

            if score is not None and int(score) < threshold:
                log(f"SKIP: Job score is {score} (< {threshold}). Not tailoring.")
                return None
        else:
            log(f"Job {job_id} not found in DB.")

    if not jd_text:
        log("No JD text available. Provide --jd-text or a valid --job_id.")
        return None

    company = company or "Unknown"
    role = role or "Unknown"
    return jd_text, company, role


def _rewrite_sections(sections: dict, jd_text: str, refs: dict, model: str) -> dict[str, str] | None:
    """Extract keywords and rewrite candidate sections, returning rewritten dict."""
    log("Extracting JD keywords via LLM...")
    keywords = extract_jd_keywords(jd_text, model)
    log(f"Keywords: {json.dumps(keywords, indent=2)}")

    rewritten: dict[str, str] = {}
    for section_name, sec_data in sections.items():
        if section_name.upper() == "HEADER":
            log(f"  SKIP (header): {section_name}")
            continue
        if section_name.upper() not in ("SUMMARY", "SKILLS"):
            if not is_section_relevant(section_name, keywords):
                log(f"  SKIP (not relevant): {section_name}")
                continue

        log(f"  Rewriting: {section_name}")
        new_text = rewrite_bullets(
            section_name=section_name,
            current_text=sec_data["content"],
            keywords=keywords,
            context_bank=refs["context_bank"],
            model=model,
        )
        rewritten[section_name] = new_text

    if not rewritten:
        log("WARNING: No sections were rewritten.")
        return None

    log(f"Rewrote {len(rewritten)} sections.")
    return rewritten


def _save_tailored_tex(tailored_tex: str, company: str, role: str) -> Path:
    """Save the tailored tex to disk alongside custom commands."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_company = safe_filename(company)
    safe_role = safe_filename(role)
    tex_filename = f"tailored_resume_{safe_company}_{safe_role}.tex"
    tex_path = OUTPUT_DIR / tex_filename

    if CUSTOM_COMMANDS.exists():
        dest = OUTPUT_DIR / "custom-commands.tex"
        dest.write_text(CUSTOM_COMMANDS.read_text(encoding="utf-8"), encoding="utf-8")

    tex_path.write_text(tailored_tex, encoding="utf-8")
    log(f"Saved: {tex_path}")
    return tex_path


# ═══════════════════════════════════════════════════════════════
#  MAIN RUN FUNCTION
# ═══════════════════════════════════════════════════════════════
def run(
    job_id: str | None = None,
    jd_text: str | None = None,
    company: str | None = None,
    role: str | None = None,
    model: str = "qwen2.5:7b",
    no_compile: bool = False,
    **kwargs,
) -> str | None:
    """
    Core resume-tailor logic. Works both standalone and when imported.

    Returns the path to the generated .tex (or .pdf) file, or None on error.
    """

    # ── 0. Validate Ollama is running ────────────────────────
    check_ollama()

    # ── 1. Load references ───────────────────────────────────
    log("Loading references...")
    refs = load_references()

    # ── 2. Get/Validate JD ───────────────────────────────────
    validation = _validate_job_for_tailoring(job_id, jd_text, company, role, refs)
    if not validation:
        return None
    jd_text, company, role = validation

    log(f"Tailoring for: {company} — {role}")

    # ── 3. Parse marker sections ─────────────────────────────
    log("Parsing LaTeX marker sections...")
    sections = parse_marker_sections(refs["base_resume_tex"])
    log(f"Found {len(sections)} sections: {list(sections.keys())}")

    if not sections:
        log("ERROR: No marker sections found in base_resume.tex")
        return None

    # ── 4. Extract JD keywords & Rewrite ─────────────────────
    rewritten = _rewrite_sections(sections, jd_text, refs, model)
    if not rewritten:
        return None

    # ── 5. Assemble and Save ─────────────────────────────────
    log("Assembling tailored .tex file...")
    tailored_tex = assemble_tailored_tex(refs["base_resume_tex"], sections, rewritten)
    tex_path = _save_tailored_tex(tailored_tex, company, role)

    # ── 7. Compile PDF ───────────────────────────────────────
    pdf_path = None
    if not no_compile:
        pdf_path = compile_pdf(tex_path)
        if not pdf_path:
            log("WARNING: PDF compilation failed — .tex file is still saved.")
    else:
        log("Skipping PDF compilation (--no-compile)")

    # ── 8. Update DB ─────────────────────────────────────────
    output_path = str(pdf_path or tex_path)
    if job_id:
        update_db(job_id, output_path)

    log(f"Done! Output: {output_path}")
    return output_path


# ═══════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tailor a LaTeX resume to match a specific JD.")
    parser.add_argument("--job_id", type=str, help="Job ID to look up in scout_jobs.db")
    parser.add_argument("--jd-text", type=str, help="JD text (alternative to --job_id)")
    parser.add_argument("--company", type=str, help="Company name (used with --jd-text)")
    parser.add_argument("--role", type=str, help="Role title (used with --jd-text)")
    parser.add_argument("--model", type=str, default="qwen2.5:7b", help="Ollama model (default: qwen2.5:7b)")
    parser.add_argument("--no-compile", action="store_true", help="Skip pdflatex compilation")

    args = parser.parse_args()

    if not args.job_id and not args.jd_text:
        parser.error("Provide either --job_id or --jd-text")

    run(
        job_id=args.job_id,
        jd_text=args.jd_text,
        company=args.company,
        role=args.role,
        model=args.model,
        no_compile=args.no_compile,
    )
