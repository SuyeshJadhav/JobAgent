import tomllib
from pathlib import Path

REFERENCES_DIR = Path(__file__).parent.parent.parent / "references"


def load_references() -> dict:
    """Load all core reference files.
    Single source of truth — import from here.
    Returns dict with keys:
      base_resume_tex, context_bank,
      candidate_profile, cover_letter_template
    """
    base_resume_path = REFERENCES_DIR / "base_resume.tex"
    if not base_resume_path.exists():
        base_resume_path = REFERENCES_DIR / "main.tex"
    base_tex = base_resume_path.read_text(encoding="utf-8")

    with open(REFERENCES_DIR / "context_bank.toml", "rb") as f:
        context_bank = tomllib.load(f)

    candidate_profile = (
        REFERENCES_DIR / "candidate_profile.md"
    ).read_text(encoding="utf-8")

    cover_letter_template = (
        REFERENCES_DIR / "cover_letter_template.md"
    ).read_text(encoding="utf-8")

    cover_letter_tex_path = REFERENCES_DIR / "cover_letter.tex"
    cover_letter_tex_template = ""
    if cover_letter_tex_path.exists():
        cover_letter_tex_template = cover_letter_tex_path.read_text(
            encoding="utf-8")

    return {
        "base_resume_tex": base_tex,
        "context_bank": context_bank,
        "candidate_profile": candidate_profile,
        "cover_letter_template": cover_letter_template,
        "cover_letter_tone": cover_letter_template,
        "cover_letter_tex_template": cover_letter_tex_template,
    }
