import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH)

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
COMPANY_SLUGS_FILE = "company_slugs.json"
