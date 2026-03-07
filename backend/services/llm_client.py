import json
from pathlib import Path
from openai import OpenAI

CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.json"

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
        api_key = settings.get("groq_api_key", "")
        if not api_key:
            raise ValueError("Groq API key is missing in settings.json")
        return OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
    else:
        raise ValueError(f"Unknown llm_provider: {provider}")

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
