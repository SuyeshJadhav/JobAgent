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


def get_llm_client() -> OpenAI:
    """
    Initializes and returns an OpenAI-compatible client based on the 
    provider (Ollama or Groq) specified in settings.

    Returns:
        OpenAI: Configured client instance.

    Raises:
        ValueError: If the provider is unknown or keys are missing.
    """
    settings = get_settings()
    provider = settings.get("llm_provider", "ollama")

    if provider == "ollama":
        base_url = settings.get("ollama_base_url", "http://localhost:11434/v1")
        return OpenAI(base_url=base_url, api_key="ollama")
    elif provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError("Groq API key is missing in .env (GROQ_API_KEY)")
        return OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
    else:
        raise ValueError(f"Unknown llm_provider: {provider}")


def get_tailor_client() -> tuple[OpenAI, str]:
    """Return tailor client/model using Groq from .env when available, else Ollama fallback."""
    settings = get_settings()
    groq_key = os.getenv("GROQ_API_KEY", "")

    if groq_key:
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key,
        )
        model = settings.get(
            "groq_tailor_model",
            "meta-llama/llama-4-scout-17b-16e-instruct",
        )
        print(f"[TAILOR] Using Groq {model}")
        return client, model

    # Fallback to Ollama when GROQ_API_KEY is not set.
    base_url = settings.get("ollama_base_url", "http://localhost:11434/v1")
    model = settings.get("ollama_model", "qwen2.5:7b")
    print(f"[TAILOR] Using Ollama {model}")
    return OpenAI(base_url=base_url, api_key="ollama"), model


def get_model_name() -> str:
    """
    Retrieves the specific model identifier to be used for LLM completions.

    Returns:
        str: Model name (e.g., 'qwen2.5:7b').
    """
    settings = get_settings()
    provider = settings.get("llm_provider", "ollama")

    if provider == "ollama":
        return settings.get("ollama_model", "qwen2.5:7b")
    elif provider == "groq":
        return "llama-3.1-8b-instant"
    else:
        raise ValueError(f"Unknown llm_provider: {provider}")


def test_connection() -> bool:
    """
    Performs a minimal health check call to the configured LLM provider.

    Returns:
        bool: True if the connection is successful.
    """
    try:
        client = get_llm_client()
        model_name = get_model_name()

        # Test connection by making a small request
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5
        )
        if response.choices:
            return True
        return False
    except Exception as e:
        print(f"Connection test failed: {e}")
        return False
