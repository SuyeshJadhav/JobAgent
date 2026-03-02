"""
Cover Letter Generator — produces a targeted, human-sounding cover letter per JD.

Usage:
    python scripts/cover_letter.py --job_id <id>
    python scripts/cover_letter.py --jd-text "JD text" --company Google --role "AI Engineer"
    python scripts/cover_letter.py --jd-text "..." --company X --role Y --no-save

Pipeline import:
    from scripts.cover_letter import run
    run(job_id="abc123")
"""

import argparse
import sqlite3
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from utils import check_ollama, llm_call, log, safe_filename

# ── Paths ────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
REFERENCES = ROOT_DIR / "references"
DB_PATH = ROOT_DIR / "scout_jobs.db"
OUTPUT_DIR = ROOT_DIR / "outputs" / "cover_letters"

CANDIDATE_PROFILE = REFERENCES / "candidate_profile.md"
COVER_LETTER_TEMPLATE = REFERENCES / "cover_letter_template.md"
CONTEXT_BANK = REFERENCES / "context_bank.toml"


# ── Reference loading ────────────────────────────────────────
def load_references() -> dict:
    """Load candidate_profile, cover_letter_template, and context_bank."""
    refs: dict = {}

    if CANDIDATE_PROFILE.exists():
        refs["candidate_profile"] = CANDIDATE_PROFILE.read_text(encoding="utf-8")
    else:
        log("WARNING: candidate_profile.md not found")
        refs["candidate_profile"] = ""

    if COVER_LETTER_TEMPLATE.exists():
        refs["cover_letter_template"] = COVER_LETTER_TEMPLATE.read_text(encoding="utf-8")
    else:
        log("WARNING: cover_letter_template.md not found")
        refs["cover_letter_template"] = ""

    if CONTEXT_BANK.exists():
        with open(CONTEXT_BANK, "rb") as f:
            refs["context_bank"] = tomllib.load(f)
    else:
        log("WARNING: context_bank.toml not found")
        refs["context_bank"] = {}

    return refs


# ── Database ─────────────────────────────────────────────────
def get_job_from_db(job_id: str) -> dict | None:
    """
    Query scout_jobs.db for a job by job_id (TEXT primary key).
    Returns dict with title, company, description, status, etc.
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


def update_db(job_id: str, cover_letter_path: str) -> None:
    """Set cover_letter_path, status='cover_ready', and last_updated in DB."""
    if not DB_PATH.exists():
        log("WARNING: Database not found — skipping DB update")
        return

    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """UPDATE jobs
               SET cover_letter_path = ?, status = 'cover_ready', last_updated = ?
               WHERE job_id = ?""",
            (cover_letter_path, datetime.now(timezone.utc).isoformat(), job_id),
        )
        conn.commit()
        log(f"DB updated: job_id={job_id} → status=cover_ready")
    finally:
        conn.close()


# ── Context extraction ───────────────────────────────────────
def _build_context_summary(context_bank: dict) -> str:
    """
    Build a concise text summary of experience + projects from context_bank
    so the LLM has real details to draw from.
    """
    parts: list[str] = []

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


# ── LLM call ──────────────────────────────────────────────────────

# llm_call() is provided by utils


def generate_cover_letter(
    jd_text: str,
    company: str,
    role: str,
    candidate_profile: str,
    cover_letter_template: str,
    context_summary: str,
    model: str,
) -> str:
    """
    Single LLM call to produce the cover letter.
    Follows the prompt pattern from skills/cover-letter/SKILL.md exactly.
    """
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

    return llm_call(
        [{"role": "system", "content": system}, {"role": "user", "content": "Generate the cover letter now."}],
        model=model,
        temperature=0.7,
    )


# ── Filename helper ──────────────────────────────────────────
# safe_filename() is provided by utils


# ═══════════════════════════════════════════════════════════════
#  MAIN RUN FUNCTION
# ═══════════════════════════════════════════════════════════════
def run(
    job_id: str | None = None,
    jd_text: str | None = None,
    company: str | None = None,
    role: str | None = None,
    model: str = "qwen2.5:7b",
    no_save: bool = False,
    **kwargs,
) -> str | None:
    """
    Core cover-letter logic. Works both standalone and when imported.

    Returns the path to the generated .md file, or None on error.
    """

    # ── 0. Validate Ollama is running ────────────────────────
    check_ollama()

    # ── 1. Load references ───────────────────────────────────
    log("Loading references...")
    refs = load_references()

    # ── 2. Get JD ────────────────────────────────────────────
    job_row = None
    if job_id and not jd_text:
        log(f"Looking up job_id={job_id} in database...")
        job_row = get_job_from_db(job_id)

        if not job_row:
            log(f"ERROR: Job {job_id} not found in DB.")
            return None

        # Validate status = 'resume_ready'
        status = job_row.get("status", "")
        if status != "resume_ready":
            log(f"SKIP: Job status is '{status}', expected 'resume_ready'. Run resume_tailor.py first.")
            return None

        jd_text = job_row.get("description", "")
        company = company or job_row.get("company", "Unknown")
        role = role or job_row.get("title", "Unknown")

    if not jd_text:
        log("ERROR: No JD text available. Provide --jd-text or a valid --job_id.")
        return None

    company = company or "Unknown"
    role = role or "Unknown"
    log(f"Generating cover letter for: {company} — {role}")

    # ── 3. Build context from context_bank ───────────────────
    context_summary = _build_context_summary(refs["context_bank"])

    # ── 4. Generate cover letter (single LLM call) ───────────
    log("Calling LLM to generate cover letter...")
    letter = generate_cover_letter(
        jd_text=jd_text,
        company=company,
        role=role,
        candidate_profile=refs["candidate_profile"],
        cover_letter_template=refs["cover_letter_template"],
        context_summary=context_summary,
        model=model,
    )

    # ── 5. Word count check ──────────────────────────────────
    word_count = len(letter.split())
    log(f"Generated letter: {word_count} words")
    if word_count > 250:
        log(f"WARNING: Letter is {word_count} words (max 250). Consider trimming.")

    # ── 6. Print the letter ──────────────────────────────────
    print("\n" + "=" * 60)
    print(letter)
    print("=" * 60 + "\n")

    # ── 7. Save output ───────────────────────────────────────
    if no_save:
        log("Skipping file save (--no-save)")
        return letter

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_company = safe_filename(company)
    safe_role = safe_filename(role)
    filename = f"cover_letter_{safe_company}_{safe_role}.md"
    out_path = OUTPUT_DIR / filename

    out_path.write_text(letter, encoding="utf-8")
    log(f"Saved: {out_path}")

    # ── 8. Update DB ─────────────────────────────────────────
    if job_id:
        update_db(job_id, str(out_path))

    log(f"Done! Output: {out_path}")
    return str(out_path)


# ═══════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a targeted cover letter for a specific job.")
    parser.add_argument("--job_id", type=str, help="Job ID to look up in scout_jobs.db")
    parser.add_argument("--jd-text", type=str, help="JD text (alternative to --job_id)")
    parser.add_argument("--company", type=str, help="Company name (used with --jd-text)")
    parser.add_argument("--role", type=str, help="Role title (used with --jd-text)")
    parser.add_argument("--model", type=str, default="qwen2.5:7b", help="Ollama model (default: qwen2.5:7b)")
    parser.add_argument("--no-save", action="store_true", help="Print letter but don't save to file or update DB")

    args = parser.parse_args()

    if not args.job_id and not args.jd_text:
        parser.error("Provide either --job_id or --jd-text")

    run(
        job_id=args.job_id,
        jd_text=args.jd_text,
        company=args.company,
        role=args.role,
        model=args.model,
        no_save=args.no_save,
    )
