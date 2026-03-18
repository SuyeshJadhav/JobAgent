import hashlib
import re
from datetime import datetime

import dateparser

SUPPORTED_JOB_TYPES = {"internship", "newgrad", "fulltime"}


def normalize_job_types(job_types: list[str]) -> tuple[list[str], list[str]]:
    recognized = []
    ignored = []
    for jt in job_types:
        if jt.lower() in SUPPORTED_JOB_TYPES:
            recognized.append(jt.lower())
        else:
            ignored.append(jt)
    return recognized, ignored


def standardize_date(date_val) -> str:
    if not date_val:
        return datetime.now().strftime("%Y-%m-%d")

    if isinstance(date_val, (int, float)):
        if date_val > 1e11:
            date_val = date_val / 1000.0
        try:
            from datetime import timezone

            return datetime.fromtimestamp(date_val, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception as e:
            print(f"[WARN] Could not parse numeric timestamp {date_val}: {e}")
            return datetime.now().strftime("%Y-%m-%d")

    if isinstance(date_val, str):
        date_str = date_val.strip()

        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return date_str

        try:
            parsed = dateparser.parse(
                date_str,
                settings={"TIMEZONE": "UTC",
                          "RETURN_AS_TIMEZONE_AWARE": False},
            )
            if parsed:
                return parsed.strftime("%Y-%m-%d")
        except Exception as e:
            print(f"[WARN] Error standardizing date string '{date_str}': {e}")

    print(f"[WARN] Unparseable date format: {date_val}")
    return datetime.now().strftime("%Y-%m-%d")


def deduplicate_jobs(jobs: list[dict]) -> list[dict]:
    seen = {}

    def normalize_company(c: str) -> str:
        if not c:
            return ""
        c = c.lower()
        c = re.sub(r"\b(inc\.?|llc|ltd\.?|corp\.?|corporation)\b", "", c)
        c = re.sub(r"[^\w\s]", "", c)
        return re.sub(r"\s+", " ", c).strip()

    def normalize_title(t: str) -> str:
        if not t:
            return ""
        t = t.lower()
        t = re.sub(r"[^\w\s]", "", t)
        return re.sub(r"\s+", " ", t).strip()

    for job in jobs:
        comp = normalize_company(job.get("company", ""))
        title = normalize_title(job.get("title", ""))
        loc = job.get("location", "").lower().strip()
        loc = re.sub(r"[^\w\s]", "", loc)
        loc = re.sub(r"\s+", " ", loc).strip()

        fingerprint = f"{comp}|{title}|{loc}"

        if fingerprint not in seen:
            seen[fingerprint] = job
        else:
            existing_desc = seen[fingerprint].get("description") or ""
            new_desc = job.get("description") or ""
            if len(new_desc) > len(existing_desc):
                seen[fingerprint] = job

    result = list(seen.values())
    print(f"Deduplication: {len(jobs)} jobs -> {len(result)} unique jobs")
    return result


def _is_us_or_remote(location: str | None) -> bool:
    if not location:
        return True
    location_lower = location.lower()
    return any(
        marker in location_lower
        for marker in ["usa", "united states", "u.s.", "remote"]
    )


def _title_matches_role(title: str | None, role_keyword: str) -> bool:
    if not title:
        return False
    if not role_keyword:
        return True
    return role_keyword.lower() in title.lower()


def _build_job_record(
    *,
    title: str,
    company: str,
    apply_link: str,
    location: str | None,
    date_posted,
    source: str,
    description: str = "",
    is_sponsored: bool = False,
) -> dict:
    location_str = location or "Remote"
    job_id = hashlib.sha256(
        f"{company}|{title}|{apply_link}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": location_str,
        "apply_link": apply_link,
        "description": description,
        "source": source,
        "found_at": datetime.now().isoformat(),
        "date_posted_str": standardize_date(date_posted),
        "status": "pending_scrape",
        "is_sponsored": is_sponsored,
    }
