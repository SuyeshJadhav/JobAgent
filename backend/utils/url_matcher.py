"""
Shared URL normalization and matching utilities for all routers.
Handles ATS-specific domain patterns (Workday, Greenhouse, Lever, Paradox, etc.)
"""
from urllib.parse import urlparse, parse_qsl, urlencode
import hashlib
import re

def normalize_url(url: str) -> str:
    """Normalize domain and path while preserving critical job identification query params."""
    if not url:
        return ""
    
    # Ensure scheme for urlparse
    if not url.startswith('http'):
        url = 'https://' + url
        
    parsed = urlparse(url)
    
    # Keep important query params that might define the job (like paradox.ai uses job_id)
    important_params = {'job_id', 'jobid', 'req', 'id', 'guid', 'gh_jid', 'job', 'j', 'jobv2'}
    qs = parse_qsl(parsed.query)
    kept_qs = [(k, v) for k, v in qs if k.lower() in important_params]
    
    new_query = urlencode(kept_qs)
    
    # Reconstruct url
    norm = parsed.netloc + parsed.path.rstrip('/')
    if new_query:
        norm += '?' + new_query
        
    return norm.lower()


def generate_deterministic_job_id(company_name: str, url: str) -> str:
    """
    Generate a deterministic 12-character MD5 hash based on company name and normalized ATS ID/URL.
    """
    if not url:
        return ""
        
    extracted_id = ""
    # Workday regex: e.g. /job/.../Title_JR-12345
    wd_match = re.search(r'_(JR-\d+(?:-\d+)?)', url, re.IGNORECASE)
    
    if wd_match:
        extracted_id = wd_match.group(1).upper()
    else:
        # Fallback / Greenhouse / Lever
        parsed = urlparse(url if url.startswith('http') else 'https://' + url)
        path = parsed.path.rstrip('/')
        # Strip language tags like /en-us or /en_US
        path = re.sub(r'^/[a-z]{2}(?:[-_][a-z]{2,3})?(?=/|$)', '', path, flags=re.IGNORECASE)
        extracted_id = path.strip('/')
        
    comp = (company_name or "").strip().lower()
    raw_string = f"{comp}::{extracted_id.lower()}"
    return hashlib.md5(raw_string.encode('utf-8')).hexdigest()[:12]


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

    # Tier 2: Substring containment (covers path prefixes, like adding /apply)
    if norm_a in norm_b or norm_b in norm_a:
        return True

    return False


def find_job_by_url(jobs: list[dict], url: str) -> dict | None:
    """Find the first job in the list whose apply_link matches the given URL."""
    for j in jobs:
        link = j.get("apply_link", "")
        if link and urls_match(link, url):
            return j
    return None
