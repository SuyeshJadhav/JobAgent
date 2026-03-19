import json
import os
from pathlib import Path

from fastapi import APIRouter
from backend.services.llm_client import test_connection, get_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.json"
ROOT_ENV_PATH = Path(__file__).parent.parent.parent / ".env"


@router.get("")
def read_settings():
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@router.post("")
def update_settings(settings: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

    # Test LLM connection with the new settings
    conn = test_connection()

    return {"saved": True, "llm_ok": conn["ok"], "llm_details": conn}


@router.get("/providers")
def get_providers():
    """
    Returns available LLM providers, their models, and connection status.
    Used by the extension popup and frontend to build the provider selector.
    """
    groq_key = os.getenv("GROQ_API_KEY", "")

    providers = {
        "groq": {
            "name": "Groq Cloud",
            "description": "Fast cloud inference via Groq. Free tier available. No GPU needed.",
            "requires_api_key": True,
            "has_api_key": bool(groq_key),
            "models": [
                "meta-llama/llama-4-scout-17b-16e-instruct",
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
                "gemma2-9b-it",
                "mixtral-8x7b-32768",
            ],
        },
        "ollama": {
            "name": "Ollama (Local)",
            "description": "Run models locally. Requires Ollama installed. GPU recommended.",
            "requires_api_key": False,
            "has_api_key": True,  # Not applicable
            "is_running": False,
            "models": [],
        },
    }

    # Dynamically fetch locally installed Ollama models
    try:
        import requests

        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        if resp.ok:
            data = resp.json()
            providers["ollama"]["models"] = [
                m["name"] for m in data.get("models", [])
            ]
            providers["ollama"]["is_running"] = True
    except Exception:
        providers["ollama"]["is_running"] = False

    # Include current settings for the UI to pre-select
    try:
        current = get_settings()
        providers["current_provider"] = current.get("llm_provider", "groq")
        providers["current_model"] = (
            current.get("groq_model") if current.get("llm_provider") == "groq"
            else current.get("ollama_model", "qwen2.5:7b")
        )
    except Exception:
        providers["current_provider"] = "groq"
        providers["current_model"] = "meta-llama/llama-4-scout-17b-16e-instruct"

    return providers


@router.post("/api_key")
def update_api_key(payload: dict):
    """
    Update an API key in the .env file and reload it into the process.
    Expects: { "key_name": "GROQ_API_KEY", "key_value": "gsk_..." }
    """
    key_name = payload.get("key_name", "GROQ_API_KEY")
    key_value = payload.get("key_value", "").strip()

    if not key_name or not key_value:
        return {"saved": False, "error": "key_name and key_value are required"}

    # Read existing .env, update the target key, write back
    env_lines = []
    found = False

    if ROOT_ENV_PATH.exists():
        with open(ROOT_ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith(f"{key_name}="):
                    env_lines.append(f"{key_name}={key_value}\n")
                    found = True
                else:
                    env_lines.append(line)

    if not found:
        env_lines.append(f"{key_name}={key_value}\n")

    with open(ROOT_ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(env_lines)

    # Hot-reload the key into the current process
    os.environ[key_name] = key_value

    # Test connection with the new key
    conn = test_connection()
    return {"saved": True, "connection_ok": conn["ok"], "details": conn}


@router.get("/test_connection")
def test_llm_connection():
    """Quick health check endpoint for the configured LLM provider."""
    return test_connection()
