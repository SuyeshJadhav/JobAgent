"""
Shared URL normalization and matching utilities for all routers.
Handles ATS-specific domain patterns (Workday, Greenhouse, Lever, Paradox, etc.)
"""
from urllib.parse import urlparse


def normalize_url(url: str) -> str:
    """Strip protocol, query params, fragments, and trailing slashes."""
    if not url:
        return ""
    url = url.split("?")[0].split("#")[0].rstrip("/")
    url = url.replace("https://", "").replace("http://", "")
    return url


def extract_ats_domain(url: str) -> str:
    """
    Extract the 'company-specific ATS key' from a URL.
    This groups all pages within the same company's ATS as a single key.

    Examples:
        fedex.paradox.ai/co/.../Job?...  →  fedex.paradox.ai
        veradigm.wd12.myworkdayjobs.com/VR/job/...  →  veradigm.wd12.myworkdayjobs.com
        boards.greenhouse.io/openai/jobs/123  →  boards.greenhouse.io/openai
        jobs.lever.co/netflix/abc123  →  jobs.lever.co/netflix
        careers.google.com/apply/...  →  careers.google.com
    """
    if not url:
        return ""
    # Ensure we have a scheme for urlparse
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path.strip("/")

    # Greenhouse: company is first path segment
    if "greenhouse.io" in host:
        first_seg = path.split("/")[0] if path else ""
        return f"{host}/{first_seg}" if first_seg else host

    # Lever: company is first path segment
    if "lever.co" in host:
        first_seg = path.split("/")[0] if path else ""
        return f"{host}/{first_seg}" if first_seg else host

    # For everything else (Workday, Paradox, SmartRecruiters, etc.),
    # the subdomain IS the company identifier — hostname is sufficient.
    return host


def urls_match(url_a: str, url_b: str) -> bool:
    """
    Determine if two URLs refer to the same tracked job.

    Matching tiers (in order):
      1. Exact normalized match
      2. Substring containment (one is a prefix/suffix of the other)
      3. ATS domain match (same company portal)
    """
    if not url_a or not url_b:
        return False

    norm_a = normalize_url(url_a)
    norm_b = normalize_url(url_b)

    # Tier 1: Exact match
    if norm_a == norm_b:
        return True

    # Tier 2: Substring containment (covers path prefixes)
    if norm_a in norm_b or norm_b in norm_a:
        return True

    # Tier 3: ATS domain match (same company portal, different pages)
    domain_a = extract_ats_domain(url_a)
    domain_b = extract_ats_domain(url_b)
    if domain_a and domain_b and domain_a == domain_b:
        return True

    return False


def find_job_by_url(jobs: list[dict], url: str) -> dict | None:
    """Find the first job in the list whose apply_link matches the given URL."""
    for j in jobs:
        link = j.get("apply_link", "")
        if link and urls_match(link, url):
            return j
    return None
