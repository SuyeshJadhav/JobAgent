import hashlib
import json
import urllib.request
from datetime import datetime
from pathlib import Path

SIMPLIFY_INTERN_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json"
SIMPLIFY_NEWGRAD_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"

ROLE_KEYWORDS = [
    "engineer", "scientist", "ml", "ai", "data",
    "software", "backend", "fullstack", "research",
    "python", "llm", "machine learning", "applied"
]

SENIORITY_KEYWORDS = [
    "senior", "sr.", "lead", "staff", "principal",
    "manager", "director", "head of", "vp"
]

def _get_settings() -> dict:
    settings_path = Path(__file__).parent.parent / "config" / "settings.json"
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def fetch_simplify_jobs(job_types: list[str]) -> list[dict]:
    settings = _get_settings()
    blocked_companies = [c.lower() for c in settings.get("blocked_companies", [])]
    blocked_keywords = [k.lower() for k in settings.get("blocked_keywords", [])]

    urls_to_fetch = []
    for jt in job_types:
        if jt.lower() == "internship":
            urls_to_fetch.append(SIMPLIFY_INTERN_URL)
        elif jt.lower() == "newgrad":
            urls_to_fetch.append(SIMPLIFY_NEWGRAD_URL)
        elif jt.lower() == "fulltime":
            continue

    normalized_jobs = []

    for url in urls_to_fetch:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())

            for item in data:
                # 1. Skip if active=False or is_visible=False
                if not item.get("active", True) or not item.get("is_visible", True):
                    continue

                # 2. Skip if no url/apply link
                apply_link = item.get("url")
                if not apply_link:
                    continue

                title = item.get("title", "")
                company = item.get("company_name", "")

                title_lower = title.lower()

                # 3. Role filter
                if not any(kw.lower() in title_lower for kw in ROLE_KEYWORDS):
                    continue

                # 4. Seniority filter
                # Simple boundary check to avoid "data" matching "database", though instructions said "contains ANY of"
                # Using simple membership as instructed but word boundaries for "vp" and "ai" makes sense.
                # We will stick to simple string containment first to follow instructions literally, except we expect standard strings.
                if any(sr_kw.lower() in title_lower for sr_kw in SENIORITY_KEYWORDS):
                    continue

                # 5. Spam filter
                company_lower = company.lower()
                is_spam = False
                if company_lower in blocked_companies:
                    is_spam = True
                if any(bk.lower() in company_lower for bk in blocked_keywords):
                    is_spam = True
                
                if is_spam:
                    continue
                
                # Normalize
                job_id = item.get("id")
                if not job_id:
                    unique_str = f"{company}{title}"
                    job_id = hashlib.sha256(unique_str.encode("utf-8")).hexdigest()[:16]
                else:
                    job_id = str(job_id)

                locations = item.get("locations", [])
                location = locations[0] if locations else "Remote"
                description = item.get("description", "")

                normalized_jobs.append({
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "location": location,
                    "apply_link": apply_link,
                    "description": description,
                    "source": "simplify",
                    "found_at": datetime.now().isoformat(),
                    "status": "found"
                })

        except Exception as e:
            print(f"Error fetching from {url}: {e}")

    return normalized_jobs
