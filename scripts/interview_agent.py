"""
Interview Agent — interacts with candidate to pull out project context and saves to context_bank.

Usage:
    python scripts/interview_agent.py
"""

import argparse
import json
import re
import shutil
import tomllib
from pathlib import Path

from utils import check_ollama, llm_call, log

# ── Paths ────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
CONTEXT_BANK = ROOT_DIR / "references" / "context_bank.toml"


def _polish_answers(raw_answers: dict, model: str) -> dict:
    """Use Ollama to polish the raw answers into solid statements without inventing data."""
    system = (
        "You are a helpful assistant. You are given raw notes about a project written casually by a developer.\n"
        "Your job is to polish them into clean, concise statements that describe what was done, "
        "what problem was solved, and what the impact or metrics were.\n"
        "DO NOT INVENT ANY NEW INFORMATION OR NUMBERS. Just clean up the language.\n"
        "Return the polished data as a JSON object with keys: "
        "'what_did_you_build', 'how_it_works', 'metric_or_impact', 'what_was_hard'."
    )

    user = f"Raw project notes:\n{raw_answers}"

    result = llm_call(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=model,
        temperature=0.4,
    )

    result = result.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(result)
    except json.JSONDecodeError:
        log("WARNING: Failed to parse polished output. Using raw answers.")
        return raw_answers


# ── Interactive CLI ──────────────────────────────────────────
def _run_interview() -> dict:
    """Ask the user 5 questions about a project/experience."""
    print("\n" + "=" * 60)
    print("  INTERVIEW AGENT — Add a new project or experience")
    print("=" * 60)

    is_exp = input("Is this a work experience (E) or a project (P)? [E/P]: ").strip().upper() == "E"

    if is_exp:
        company = input("Company name: ").strip()
        role = input("Role title: ").strip()
        dates = input("Dates (e.g., Jun 2024 - Aug 2024): ").strip()
    else:
        name = input("Project name: ").strip()
        tools_used = input("Tools/stack used (comma-separated): ").strip()

    print("\nGreat. Let's dig into the details. (Keep answers casual, raw numbers are fine)")

    q1 = input("1. What exactly did you build?\n> ").strip()
    q2 = input("2. What tools/algorithms did you use?\n> ").strip()
    q3 = input("3. What specific problem did this solve?\n> ").strip()
    q4 = input("4. Can you quantify the impact? (e.g. latency reduced by X, handled Y requests)\n> ").strip()
    q5 = input("5. What was the hardest part about building this?\n> ").strip()

    raw_answers = {
        "what_did_you_build": q1,
        "tools_used": q2,
        "what_problem_solved": q3,
        "impact_or_metrics": q4,
        "what_was_hard": q5,
    }

    return {
        "is_exp": is_exp,
        "meta": {"company": company, "role": role, "dates": dates}
        if is_exp
        else {"name": name, "tools_used": tools_used},
        "raw_answers": raw_answers,
    }


def _save_to_toml(entry: dict, polished: dict) -> None:
    """
    Append the polished entry to context_bank.toml.
    Safety protocol:
      1. Backup original file
      2. Write appended version
      3. Validate TOML is parseable
      4. Restore backup if validation fails
    """
    if not CONTEXT_BANK.exists():
        log(f"ERROR: {CONTEXT_BANK} not found.")
        return

    # ── 1. Build append content ──────────────────────────────
    parts = []

    if entry["is_exp"]:
        parts.append("\n[[experience]]")
        parts.append(f'company = "{entry["meta"].get("company", "")}"')
        parts.append(f'role    = "{entry["meta"].get("role", "")}"')
        parts.append(f'dates   = "{entry["meta"].get("dates", "")}"')

        parts.append("\n  [[experience.project_1]]")
        parts.append(f'  what_did_you_build    = "{polished.get("what_did_you_build", "")}"')
        parts.append(f'  tools_used            = "{entry["raw_answers"].get("tools_used", "")}"')
        parts.append(f'  how_it_works          = "{polished.get("how_it_works", "")}"')
        parts.append(f'  metric                = "{polished.get("metric_or_impact", "")}"')
        parts.append(f'  what_was_hard         = "{polished.get("what_was_hard", "")}"')
    else:
        parts.append("\n[[project]]")
        parts.append(f'name       = "{entry["meta"].get("name", "")}"')
        parts.append(f'tools_used = "{entry["meta"].get("tools_used", "")}"')

        parts.append("\n  [[project.bullet_1]]")
        parts.append(f'  what_did_you_build    = "{polished.get("what_did_you_build", "")}"')
        parts.append(f'  how_it_works          = "{polished.get("how_it_works", "")}"')
        parts.append(f'  metric                = "{polished.get("metric_or_impact", "")}"')
        parts.append(f'  what_was_hard         = "{polished.get("what_was_hard", "")}"')

    append_str = "\n".join(parts) + "\n"

    # ── 2. Escape inner double-quotes to prevent TOML breakage ──
    # (LLM answers may contain quotes -- escape them)
    safe_append = append_str.replace('\\"', '"')  # normalise first
    # Re-escape any unescaped quotes inside values
    safe_append = re.sub(
        r'(= ")(.+?)(")\ *$',
        lambda m: m.group(1) + m.group(2).replace('"', '\\"') + m.group(3),
        safe_append,
        flags=re.MULTILINE,
    )

    # ── 3. Backup original ───────────────────────────────────
    backup_path = CONTEXT_BANK.with_suffix(".toml.bak")
    shutil.copy2(CONTEXT_BANK, backup_path)
    log(f"Backup created: {backup_path.name}")

    # ── 4. Write appended file ───────────────────────────────
    new_content = CONTEXT_BANK.read_text(encoding="utf-8") + safe_append
    CONTEXT_BANK.write_text(new_content, encoding="utf-8")

    # ── 5. Validate TOML ────────────────────────────────────
    try:
        with open(CONTEXT_BANK, "rb") as f:
            tomllib.load(f)
        log("TOML validation passed. Entry saved successfully.")
        # Clean up backup on success
        backup_path.unlink(missing_ok=True)
    except tomllib.TOMLDecodeError as e:
        log(f"ERROR: TOML validation failed: {e}")
        log("Restoring backup...")
        shutil.copy2(backup_path, CONTEXT_BANK)
        log("Backup restored. context_bank.toml is unchanged.")
        log("The problematic content was:")
        print(safe_append)


# ═══════════════════════════════════════════════════════════════
#  MAIN RUN FUNCTION
# ═══════════════════════════════════════════════════════════════
def run(model: str = "qwen2.5:7b", **kwargs) -> None:
    """Core interview logic."""

    # ── 0. Validate Ollama is running ────────────────────────
    check_ollama()

    # 1. Ask questions
    entry = _run_interview()

    # 2. Polish
    log(f"Polishing answers with {model}...")
    polished = _polish_answers(entry["raw_answers"], model)

    # 3. Save
    _save_to_toml(entry, polished)


# ═══════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Interactive CLI to safely add project context.")
    parser.add_argument("--model", type=str, default="qwen2.5:7b", help="Ollama model to use for polishing")

    args = parser.parse_args()

    run(model=args.model)
