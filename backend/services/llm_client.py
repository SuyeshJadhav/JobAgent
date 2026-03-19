import json
import os
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.json"
ROOT_ENV_PATH = Path(__file__).parent.parent.parent / ".env"

# Load environment variables once for API key resolution.
load_dotenv(dotenv_path=ROOT_ENV_PATH)


def get_settings() -> dict:
    """
    Loads the global application settings from config/settings.json.

    Returns:
        dict: Settings dictionary.

    Raises:
        FileNotFoundError: If the settings file is missing.
    """
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Configuration file not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Unified LLM Client ──────────────────────────────────────────────────────


def get_client_and_model() -> tuple[OpenAI, str]:
    """
    Single source of truth for obtaining an LLM client and model name.

    Reads ``llm_provider`` from *settings.json* and routes to the correct
    backend (Groq cloud or Ollama local).  Every LLM-consuming service in
    the project should call this function instead of constructing clients
    ad-hoc.

    Returns:
        tuple[OpenAI, str]: (client, model_name)

    Raises:
        ValueError: If the provider is unknown or required keys are missing.
    """
    settings = get_settings()
    provider = settings.get("llm_provider", "groq")

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError(
                "Groq API key is missing. Set GROQ_API_KEY in the .env file "
                "or switch llm_provider to 'ollama' in settings."
            )
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
        )
        model = settings.get(
            "groq_model",
            "meta-llama/llama-4-scout-17b-16e-instruct",
        )
        return client, model

    if provider == "ollama":
        base_url = settings.get("ollama_base_url", "http://localhost:11434/v1")
        model = settings.get("ollama_model", "qwen2.5:7b")
        client = OpenAI(base_url=base_url, api_key="ollama")
        return client, model

    raise ValueError(f"Unknown llm_provider: '{provider}'")


# ── Backward-compatible wrappers ─────────────────────────────────────────────
# These delegate to get_client_and_model() so that existing callers
# (scorer, cover_letter, sniper, profile_rag, resume_manager) keep working
# without any import changes.


def get_llm_client() -> OpenAI:
    """Returns only the OpenAI client (legacy helper)."""
    client, _ = get_client_and_model()
    return client


def get_model_name() -> str:
    """Returns only the model name string (legacy helper)."""
    _, model = get_client_and_model()
    return model


def get_tailor_client() -> tuple[OpenAI, str]:
    """Alias for get_client_and_model (used by resume_generators)."""
    client, model = get_client_and_model()
    print(
        f"[LLM] Using {get_settings().get('llm_provider', 'groq')} → {model}")
    return client, model


# ── Health check ─────────────────────────────────────────────────────────────


def test_connection() -> dict:
    """
    Performs a minimal health check call to the configured LLM provider.

    Returns:
        dict: {ok: bool, provider: str, model: str, error: str|None}
    """
    try:
        client, model = get_client_and_model()
        provider = get_settings().get("llm_provider", "groq")

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5,
        )
        ok = bool(response.choices)
        return {"ok": ok, "provider": provider, "model": model, "error": None}
    except Exception as e:
        print(f"Connection test failed: {e}")
        return {"ok": False, "provider": "unknown", "model": "unknown", "error": str(e)}


def get_tailor_client_with_key(
    groq_api_key: str = None
) -> tuple[OpenAI, str]:
    """
    Same as get_tailor_client() but accepts an optional Groq key override.

    Args:
        groq_api_key (str, optional): Groq API key provided per-request.
                                       If provided, uses it.
                                       If not, falls back to environment GROQ_API_KEY.

    Returns:
        tuple[OpenAI, str]: (client, model) tuple.
                           Uses Groq if key available, else Ollama.
    """
    if groq_api_key:
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_api_key
        )
        model = "meta-llama/llama-4-scout-17b-16e-instruct"
        return client, model

    # Fallback: check environment GROQ_API_KEY
    env_key = os.getenv("GROQ_API_KEY", "")
    if env_key:
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=env_key
        )
        model = "meta-llama/llama-4-scout-17b-16e-instruct"
        return client, model

    # Final fallback: use Ollama
    settings = get_settings()
    client = OpenAI(
        base_url=settings.get(
            "ollama_base_url",
            "http://localhost:11434/v1"
        ),
        api_key="ollama"
    )
    model = settings.get("ollama_model", "qwen2.5:7b")
    return client, model
