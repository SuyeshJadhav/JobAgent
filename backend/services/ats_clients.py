import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

from backend.config.config import COMPANY_SLUGS_FILE, SERPER_API_KEY
from backend.services.llm_client import get_settings
from backend.utils.job_normalizer import (
    _build_job_record,
    _is_us_or_remote,
    _title_matches_role,
)

logger = logging.getLogger(__name__)

ATS_DOMAINS = [
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "workable.com",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "breezy.hr",
    "recruitee.com",
    "rippling.com",
    "rippling-ats.com",
    "personio.de",
    "bamboohr.com",
    "icims.com",
    "oraclecloud.com",
    "wellfound.com",
    "workatastartup.com",
]


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


def _load_company_slugs() -> dict[str, list[str]]:
    default = {"greenhouse": [], "lever": [], "ashby": []}
    slugs_path = Path(__file__).parent.parent.parent / COMPANY_SLUGS_FILE
    if not slugs_path.exists():
        logger.warning(f"Company slugs file not found: {slugs_path}")
        return default

    try:
        with open(slugs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key in default:
            value = data.get(key, [])
            if isinstance(value, list):
                default[key] = [str(v).strip()
                                for v in value if str(v).strip()]
    except Exception as e:
        logger.warning(f"Failed reading company slugs file: {e}")

    return default


def _fetch_greenhouse_jobs(slug: str, role_keyword: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    jobs = []
    try:
        resp = requests.get(url, timeout=12)
        if resp.status_code != 200:
            return []
        payload = resp.json()
        for item in payload.get("jobs", []):
            title = item.get("title", "")
            apply_link = item.get("absolute_url")
            location = (item.get("location") or {}).get("name", "")
            if not apply_link:
                continue
            if not _title_matches_role(title, role_keyword):
                continue
            if not _is_us_or_remote(location):
                continue
            jobs.append(
                _build_job_record(
                    title=title,
                    company=slug.replace("-", " ").title(),
                    apply_link=apply_link,
                    location=location,
                    date_posted=item.get(
                        "updated_at") or item.get("created_at"),
                    source="greenhouse",
                    description=item.get("content", ""),
                )
            )
    except Exception as e:
        logger.warning(f"Greenhouse fetch failed for {slug}: {e}")
    return jobs


def _fetch_lever_jobs(slug: str, role_keyword: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    jobs = []
    try:
        resp = requests.get(url, timeout=12)
        if resp.status_code != 200:
            return []
        payload = resp.json()
        for item in payload:
            title = item.get("text", "")
            apply_link = item.get("hostedUrl")
            location = (item.get("categories") or {}).get("location", "")
            if not apply_link:
                continue
            if not _title_matches_role(title, role_keyword):
                continue
            if not _is_us_or_remote(location):
                continue
            jobs.append(
                _build_job_record(
                    title=title,
                    company=slug.replace("-", " ").title(),
                    apply_link=apply_link,
                    location=location,
                    date_posted=item.get("createdAt"),
                    source="lever",
                    description=item.get("descriptionPlain", ""),
                )
            )
    except Exception as e:
        logger.warning(f"Lever fetch failed for {slug}: {e}")
    return jobs


def _fetch_ashby_jobs(slug: str, role_keyword: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    jobs = []
    try:
        resp = requests.post(url, json={"jobPostings": True}, timeout=12)
        if resp.status_code != 200:
            return []
        payload = resp.json()
        for item in payload.get("jobPostings", []):
            title = item.get("title", "")
            apply_link = item.get("jobUrl")
            location = item.get("locationName", "")
            if not apply_link:
                continue
            if not _title_matches_role(title, role_keyword):
                continue
            if not _is_us_or_remote(location):
                continue
            jobs.append(
                _build_job_record(
                    title=title,
                    company=slug.replace("-", " ").title(),
                    apply_link=apply_link,
                    location=location,
                    date_posted=item.get(
                        "publishedDate") or item.get("createdAt"),
                    source="ashby",
                    description=item.get("description", ""),
                )
            )
    except Exception as e:
        logger.warning(f"Ashby fetch failed for {slug}: {e}")
    return jobs


def fetch_ats_jobs(role_keyword: str | None = None) -> list[dict]:
    role_keyword = role_keyword or _get_role_keyword(get_settings())
    slugs = _load_company_slugs()
    tasks = []

    with ThreadPoolExecutor(max_workers=12) as executor:
        for slug in slugs.get("greenhouse", []):
            tasks.append(executor.submit(
                _fetch_greenhouse_jobs, slug, role_keyword))
        for slug in slugs.get("lever", []):
            tasks.append(executor.submit(
                _fetch_lever_jobs, slug, role_keyword))
        for slug in slugs.get("ashby", []):
            tasks.append(executor.submit(
                _fetch_ashby_jobs, slug, role_keyword))

        results = []
        for future in as_completed(tasks):
            try:
                results.extend(future.result())
            except Exception as e:
                logger.warning(f"ATS future failed: {e}")

    return results


def _search_serper(query: str, api_key: str) -> list[str]:
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "q": query,
        "num": 10,
        "gl": "us",
        "location": "United States",
    }
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers=headers,
            json=payload,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"Serper API returned {resp.status_code}")
            return []
        data = resp.json()
        results = data.get("organic", [])
        return [r["link"] for r in results if "link" in r]
    except Exception as e:
        logger.warning(f"Serper API request failed: {e}")
        return []


def fetch_serper_fallback_jobs(
    role_keyword: str | None = None,
    max_queries: int = 5,
) -> list[dict]:
    role_keyword = role_keyword or _get_role_keyword(get_settings())
    if not SERPER_API_KEY:
        logger.warning("SERPER_API_KEY not set; skipping Serper fallback")
        return []

    queries = [
        f'"{role_keyword}" site:myworkdayjobs.com',
        f'"{role_keyword}" site:icims.com',
        f'"{role_keyword}" site:smartrecruiters.com',
    ][: max(0, max_queries)]

    found_jobs = []
    seen_urls = set()

    for query in queries:
        candidate_urls = _search_serper(query, SERPER_API_KEY)
        for actual_url in candidate_urls:
            if actual_url in seen_urls:
                continue

            if any(
                blocked in actual_url.lower()
                for blocked in ["google.com", "bing.com", "linkedin.com/search", "indeed.com"]
            ):
                continue

            is_job_link = any(domain in actual_url for domain in ATS_DOMAINS)

            if not is_job_link:
                normalized_url = actual_url.lower()
                from urllib.parse import urlparse as _urlparse

                parsed = _urlparse(actual_url)
                netloc = parsed.netloc.lower()
                if any(
                    term in normalized_url
                    for term in ["/careers/", "/jobs/", "/apply/", "/career/"]
                ) or any(
                    sub in netloc for sub in ["jobs.", "careers.", "people.", "talent."]
                ):
                    is_job_link = True

            if not is_job_link:
                continue

            seen_urls.add(actual_url)
            company = extract_company_from_url(actual_url)
            found_jobs.append(
                _build_job_record(
                    title=role_keyword,
                    company=company,
                    apply_link=actual_url,
                    location="United States",
                    date_posted=datetime.now().isoformat(),
                    source="serper",
                    description="",
                )
            )

    return found_jobs
