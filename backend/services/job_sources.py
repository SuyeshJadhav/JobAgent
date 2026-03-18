import json
import urllib.request

from backend.services.ats_clients import fetch_ats_jobs, fetch_serper_fallback_jobs
from backend.services.llm_client import get_settings
from backend.utils.job_normalizer import _build_job_record, _is_us_or_remote, _title_matches_role, deduplicate_jobs, normalize_job_types, standardize_date

SIMPLIFY_INTERN_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json"


def _get_role_keyword(settings: dict | None = None) -> str:
    settings = settings or get_settings()
    for key in ["role_keyword", "search_role", "target_role", "role"]:
        value = settings.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Software Engineer Internship"


def extract_company_from_url(url: str) -> str:
    if not url:
        return "Unknown"

    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.strip("/")
        parts = path.split("/")

        subdomain_ats = [
            "myworkdayjobs.com",
            "breezy.hr",
            "recruitee.com",
            "rippling-ats.com",
            "personio.de",
            "bamboohr.com",
        ]
        for ats in subdomain_ats:
            if ats in netloc:
                company_part = netloc.split(f".{ats}")[0]
                if company_part and company_part != "www":
                    return company_part.replace("-", " ").replace("_", " ").title()

        if "jobs.lever.co" in netloc and len(parts) > 0:
            return parts[0].replace("-", " ").title()
        if "greenhouse.io" in netloc and len(parts) > 0:
            return parts[0].replace("-", " ").title()
        if "jobs.ashbyhq.com" in netloc and len(parts) > 0:
            return parts[0].replace("-", " ").title()
        if "apply.workable.com" in netloc and len(parts) > 0:
            return parts[0].replace("-", " ").title()
        if "smartrecruiters.com" in netloc and len(parts) > 1:
            return parts[1].replace("-", " ").title()
        if "icims.com" in netloc:
            return netloc.split(".")[0].replace("-", " ").title()
        if "oraclecloud.com" in netloc:
            return netloc.split(".")[0].replace("-", " ").title()
        if "wellfound.com" in netloc:
            return "Wellfound"
        if "workatastartup.com" in netloc:
            return "Y Combinator Startup"

        domain_parts = netloc.split(".")
        if len(domain_parts) >= 2 and domain_parts[-2] not in ["google", "bing", "yahoo"]:
            return domain_parts[-2].replace("-", " ").title()

        return "Unknown"
    except Exception:
        return "Unknown"


def fetch_simplify_jobs(
    job_types: list[str] | None = None,
    role_keyword: str | None = None,
) -> list[dict]:
    role_keyword = role_keyword or _get_role_keyword(get_settings())
    normalized_jobs = []

    try:
        req = urllib.request.Request(
            SIMPLIFY_INTERN_URL, headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())

        for item in data:
            title = item.get("title", "")
            company = item.get("company_name") or item.get(
                "company") or "Unknown"
            apply_link = item.get("url")
            location_val = item.get("location")
            if not location_val:
                locations = item.get("locations", [])
                location_val = locations[0] if locations else ""

            if not apply_link:
                continue
            if not _title_matches_role(title, role_keyword):
                continue
            if not _is_us_or_remote(location_val):
                continue

            normalized_jobs.append(
                _build_job_record(
                    title=title,
                    company=company,
                    apply_link=apply_link,
                    location=location_val,
                    date_posted=item.get(
                        "date_posted") or item.get("date_updated"),
                    source="simplify",
                    description=item.get("description", ""),
                    is_sponsored=False,
                )
            )
    except Exception as e:
        print(f"Error fetching from {SIMPLIFY_INTERN_URL}: {e}")

    return normalized_jobs


def fetch_all_scout_sources(
    job_types: list[str] | None = None,
    role_keyword: str | None = None,
    max_serper_queries: int = 5,
) -> dict:
    role_keyword = role_keyword or _get_role_keyword(get_settings())

    simplify_jobs = fetch_simplify_jobs(
        job_types=job_types, role_keyword=role_keyword)
    ats_jobs = fetch_ats_jobs(role_keyword=role_keyword)
    serper_jobs = fetch_serper_fallback_jobs(
        role_keyword=role_keyword,
        max_queries=max_serper_queries,
    )

    merged = simplify_jobs + ats_jobs + serper_jobs
    return {
        "all_jobs": merged,
        "simplify_count": len(simplify_jobs),
        "ats_count": len(ats_jobs),
        "serper_count": len(serper_jobs),
    }
