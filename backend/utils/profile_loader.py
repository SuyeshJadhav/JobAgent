from pathlib import Path

PROFILE_DIR = Path(__file__).parent.parent.parent / "profile"


def load_profile_file(filename: str) -> str:
    """Load a profile markdown file.
    Single source of truth — import from here."""
    path = PROFILE_DIR / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
