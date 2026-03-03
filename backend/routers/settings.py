import json
from pathlib import Path

from fastapi import APIRouter
from backend.services.llm_client import test_connection, get_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.json"

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
        
    results = {"saved": True, "llm_ok": False}
    
    # Test LLM connection
    results["llm_ok"] = test_connection()
        
    return results
