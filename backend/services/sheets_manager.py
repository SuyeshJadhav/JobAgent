import pandas as pd
from pathlib import Path
import gspread

ROOT_DIR = Path(__file__).parent.parent.parent
CREDENTIALS_FILE = ROOT_DIR / "credentials.json"
EXCEL_FALLBACK = ROOT_DIR / "backend" / "tracked_jobs.xlsx"

class GoogleSheetsManager:
    def __init__(self):
        self.client = None
        self.sheet = None
        if CREDENTIALS_FILE.exists():
            try:
                self.client = gspread.service_account(filename=str(CREDENTIALS_FILE))
                self.sheet = self.client.open("JobAgent Tracker").sheet1
            except Exception as e:
                print(f"Failed to initialize gspread: {e}")
                self.client = None

    def append_job_row(self, title: str, company: str, url: str, status: str, date_added: str):
        row = [title, company, url, status, date_added]
        if self.client and self.sheet:
            try:
                self.sheet.append_row(row)
                return True
            except Exception as e:
                print(f"Error appending to Google Sheets: {e}")
                self._fallback_to_excel(row)
                return False
        else:
            self._fallback_to_excel(row)
            return False

    def _fallback_to_excel(self, row):
        columns = ["Title", "Company", "URL", "Status", "Date Added"]
        try:
            EXCEL_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
            if EXCEL_FALLBACK.exists():
                df = pd.read_excel(EXCEL_FALLBACK)
                new_row = pd.DataFrame([row], columns=columns)
                df = pd.concat([df, new_row], ignore_index=True)
            else:
                df = pd.DataFrame([row], columns=columns)
            
            df.to_excel(EXCEL_FALLBACK, index=False)
        except Exception as e:
            print(f"Error saving to fallback Excel: {e}")
