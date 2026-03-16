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
                self.client = gspread.service_account(
                    filename=str(CREDENTIALS_FILE))
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
                print(f"[SheetsManager] Failed to append row: {e}")
                return False
        else:
            return False

    def get_existing_urls(self) -> set:
        """Fetch all URLs already in the sheet (column 3) for deduplication."""
        if self.client and self.sheet:
            try:
                urls = self.sheet.col_values(3)  # Column C = URL
                return set(urls[1:])  # Skip header row
            except Exception as e:
                print(f"Error fetching existing URLs from Sheets: {e}")
                return set()
        return set()

    def batch_append_job_rows(self, jobs: list[dict]) -> dict:
        """Batch-add jobs to the sheet, skipping duplicates by URL.

        Each job dict must have: title, company, url, status, date_added.
        Returns {"added": int, "skipped": int}.
        """
        existing_urls = self.get_existing_urls()
        rows_to_add = []
        skipped = 0

        for job in jobs:
            if job["url"] in existing_urls:
                skipped += 1
                continue
            rows_to_add.append([
                job["title"], job["company"], job["url"],
                job["status"], job["date_added"]
            ])
            existing_urls.add(job["url"])  # Prevent intra-batch dupes

        if not rows_to_add:
            return {"added": 0, "skipped": skipped}

        if self.client and self.sheet:
            try:
                self.sheet.append_rows(rows_to_add)
                return {"added": len(rows_to_add), "skipped": skipped}
            except Exception as e:
                print(f"Error batch-appending to Google Sheets: {e}")
                return {"added": len(rows_to_add), "skipped": skipped}
        else:
            return {"added": len(rows_to_add), "skipped": skipped}
