"""
Shared utilities for the JobAgent pipeline.

Provides:
    log()                  — timestamped console output
    llm_call()             — single LLM round-trip via local Ollama
    check_ollama()         — liveness check; sys.exit on failure
    safe_filename()        — sanitise arbitrary text for use in filenames
    read_score_threshold() — parse 'Score Threshold: N' from a profile string
"""

import re
import subprocess
import sys
from datetime import datetime

# ── Ollama connection ────────────────────────────────────────
OLLAMA_BASE_URL = "http://localhost:11434/v1"


# ── Logging ──────────────────────────────────────────────────
def log(msg: str) -> None:
    """Print a timestamped log line to stdout."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ── LLM bridge ───────────────────────────────────────────────
def llm_call(messages: list[dict], model: str, temperature: float) -> str:
    """
    Single OpenAI-compatible chat completion using the local Ollama server.
    Returns the assistant message content as a string.
    """
    from openai import OpenAI

    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    return response.choices[0].message.content.strip()


# ── Ollama health check ──────────────────────────────────────
def check_ollama() -> None:
    """Exit with a clear error message if the Ollama server is not running."""
    try:
        subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit("ERROR: Ollama server is not running or not installed. Please start ollama first.")


# ── Filename helper ──────────────────────────────────────────
def safe_filename(text: str) -> str:
    """Turn arbitrary text into a safe filename component."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_")


# ── Score threshold reader ───────────────────────────────────
def read_score_threshold(profile_text: str, default: int = 6) -> int:
    """
    Parse 'Score Threshold: N' from a candidate profile string.
    Falls back to `default` (6) if the line is absent.
    """
    match = re.search(
        r"^\s*Score Threshold\s*:\s*(\d+)",
        profile_text,
        re.MULTILINE | re.IGNORECASE,
    )
    if match:
        threshold = int(match.group(1))
        log(f"Score threshold read from profile: {threshold}")
        return threshold
    return default
