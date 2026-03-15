import hashlib
import json
import urllib.request
import time
import re
from datetime import datetime
from pathlib import Path

import dateparser
from scrapling import StealthyFetcher

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


SUPPORTED_JOB_TYPES = {"internship", "newgrad", "fulltime"}


def normalize_job_types(job_types: list[str]) -> tuple[list[str], list[str]]:
    """
    Validates and normalizes a list of job type strings against supported types.

    Args:
        job_types: List of job type strings (e.g. ["internship", "newgrad"]).

    Returns:
        A tuple of (recognized_job_types, ignored_job_types).
    """
    recognized = []
    ignored = []
    for jt in job_types:
        if jt.lower() in SUPPORTED_JOB_TYPES:
            recognized.append(jt.lower())
        else:
            ignored.append(jt)
    return recognized, ignored

def standardize_date(date_val) -> str:
    """
    Standardizes various date formats into YYYY-MM-DD string.
    
    Handles:
    - Unix timestamps (ms and s)
    - Relative dates ("2 days ago")
    - ISO dates ("2026-01-15T10:30:00Z")
    - Pre-formatted dates ("2026-01-15")
    """
    if not date_val:
        return datetime.now().strftime("%Y-%m-%d")

    # Handle numeric timestamps (Unix epoch)
    if isinstance(date_val, (int, float)):
        # If it's in milliseconds (e.g., SimplifyJobs), it'll be > 1e11
        if date_val > 1e11:
            date_val = date_val / 1000.0
        try:
            from datetime import timezone
            return datetime.fromtimestamp(date_val, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception as e:
            print(f"[WARN] Could not parse numeric timestamp {date_val}: {e}")
            return datetime.now().strftime("%Y-%m-%d")

    # Handle string dates
    if isinstance(date_val, str):
        date_str = date_val.strip()
        
        # Fast path for already formatted YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return date_str
            
        try:
            parsed = dateparser.parse(date_str, settings={'TIMEZONE': 'UTC', 'RETURN_AS_TIMEZONE_AWARE': False})
            if parsed:
                return parsed.strftime("%Y-%m-%d")
        except Exception as e:
            print(f"[WARN] Error standardizing date string '{date_str}': {e}")
            
    print(f"[WARN] Unparseable date format: {date_val}")
    return datetime.now().strftime("%Y-%m-%d")

def deduplicate_jobs(jobs: list[dict]) -> list[dict]:
    """
    Remove duplicate jobs based on normalized company + title + location fingerprint.
    When duplicates are found, keeps the one with the longest description.
    """
    seen = {}
    
    def normalize_company(c: str) -> str:
        if not c: return ""
        c = c.lower()
        # Remove common suffixes
        c = re.sub(r'\b(inc\.?|llc|ltd\.?|corp\.?|corporation)\b', '', c)
        c = re.sub(r'[^\w\s]', '', c)
        return re.sub(r'\s+', ' ', c).strip()

    def normalize_title(t: str) -> str:
        if not t: return ""
        t = t.lower()
        t = re.sub(r'[^\w\s]', '', t)
        return re.sub(r'\s+', ' ', t).strip()

    for job in jobs:
        comp = normalize_company(job.get('company', ''))
        title = normalize_title(job.get('title', ''))
        loc = job.get('location', '').lower().strip()
        loc = re.sub(r'[^\w\s]', '', loc)
        loc = re.sub(r'\s+', ' ', loc).strip()
        
        fingerprint = f"{comp}|{title}|{loc}"
        
        if fingerprint not in seen:
            seen[fingerprint] = job
        else:
            # Keep the one with the longer description
            existing_desc = seen[fingerprint].get('description') or ""
            new_desc = job.get('description') or ""
            if len(new_desc) > len(existing_desc):
                seen[fingerprint] = job
                
    result = list(seen.values())
    print(f"Deduplication: {len(jobs)} jobs → {len(result)} unique jobs")
    return result

def extract_company_from_url(url: str) -> str:
    """Extracts company name from ATS URL patterns or company domains."""
    if not url: return "Unknown"
    
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.strip('/')
        parts = path.split('/')
        
        # 1. Handle Subdomain-based ATS (e.g., company.myworkdayjobs.com, company.breezy.hr)
        subdomain_ats = [
            "myworkdayjobs.com", "breezy.hr", "recruitee.com", 
            "rippling-ats.com", "personio.de", "bamboohr.com"
        ]
        for ats in subdomain_ats:
            if ats in netloc:
                # Get the part before the ATS domain
                company_part = netloc.split(f".{ats}")[0]
                if company_part and company_part != "www":
                    return company_part.replace('-', ' ').replace('_', ' ').title()

        # 2. Handle Path-based ATS
        # lever.co / greenhouse.io / ashbyhq.com / workable.com
        if 'jobs.lever.co' in netloc and len(parts) > 0:
            return parts[0].replace('-', ' ').title()
        if 'greenhouse.io' in netloc and len(parts) > 0:
            return parts[0].replace('-', ' ').title()
        if 'jobs.ashbyhq.com' in netloc and len(parts) > 0:
            return parts[0].replace('-', ' ').title()
        if 'apply.workable.com' in netloc and len(parts) > 0:
            return parts[0].replace('-', ' ').title()
        if 'smartrecruiters.com' in netloc and len(parts) > 1:
            return parts[1].replace('-', ' ').title()
            
        # 3. Fallback: Extract from the root domain for generic company sites
        # e.g., company.com/careers -> company
        domain_parts = netloc.split('.')
        if len(domain_parts) >= 2:
            # Skip common suffixes or search engine domains
            if domain_parts[-2] not in ["google", "bing", "yahoo", "duckduckgo"]:
                return domain_parts[-2].replace('-', ' ').title()
                
        return "Unknown"
    except Exception:
        return "Unknown"
    except Exception:
        return "Unknown"

def fetch_google_jobs(role: str, location: str = None, max_results: int = 50) -> list[dict]:
    """
    Uses Scrapling to automate Google searches for jobs on major ATS platforms.
    """
    settings = _get_settings()
    if not settings.get("google_search_enabled", True):
        print("Google search disabled in settings.")
        return []

    # Handle flexible location naming (especially for US)
    if location and location.lower() in ["united states", "us", "usa", "u.s."]:
        location_query = '(USA OR US OR "United States" OR "U.S.")'
    else:
        location_query = f'"{location}"' if location else ""

    location_str = f" {location_query}" if location_query else ""
    
    # Consolidate queries to reduce requests to Google (avoids 429s)
    # We combine ALL search patterns into fewer, broader requests
    queries = [
        # Major ATS Platforms Consolidated
        f'"{role}" (site:jobs.greenhouse.io OR site:boards.greenhouse.io OR site:jobs.lever.co OR site:jobs.ashbyhq.com){location_str}',
        f'"{role}" (site:apply.workable.com OR site:*.myworkdayjobs.com OR site:jobs.smartrecruiters.com OR site:*.breezy.hr){location_str}',
        # Direct Company "Careers" patterns (less likely to trigger site: limits)
        f'"{role}" (inurl:/careers/ OR inurl:/jobs/ OR intitle:"Careers"){location_str}',
    ]
    
    found_jobs = []
    seen_urls = set()
    
    print(f"Starting Google Job Discovery for role '{role}'...")
    
    fetcher = StealthyFetcher()
    
    for query in queries:
        if len(found_jobs) >= max_results:
            break
            
        print(f"Searching: {query}")
        
        try:
            # Try Google first
            search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            page = fetcher.fetch(search_url)
            
            # Check for Google rate limiting (429)
            if getattr(page, 'status_code', 0) == 429:
                print("[WARN] Google rate limit hit (429). Falling back to DuckDuckGo...")
                search_url = f"https://duckduckgo.com/html/?q={urllib.parse.quote(query)}"
                page = fetcher.fetch(search_url)

            time.sleep(5) 
            
            # Extract URLs from search results
            links = page.css("a[href]")
            for link in links:
                href = link.attrib.get('href')
                if not href: continue
                
                # Handle Google redirect URLs (e.g. /url?q=...)
                actual_url = href
                if href.startswith("/url?q="):
                    from urllib.parse import parse_qs, urlparse
                    parsed = urlparse(href)
                    qs = parse_qs(parsed.query)
                    if 'q' in qs:
                        actual_url = qs['q'][0]
                        
                if not actual_url.startswith("http"): continue
                
                print(f"Checking URL: {actual_url}") # Debug: See all links found
                
                # Broad detection: Include ATS domains or direct career pages
                ats_domains = [
                    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
                    "myworkdayjobs.com", "smartrecruiters.com", "breezy.hr",
                    "recruitee.com", "rippling-ats.com", "personio.de", "bamboohr.com"
                ]
                
                is_job_link = any(domain in actual_url for domain in ats_domains)
                
                # Heuristic for direct company pages (if we use the generic dorks)
                if not is_job_link:
                    normalized_url = actual_url.lower()
                    if any(term in normalized_url for term in ["/careers/", "/jobs/", "/apply/"]):
                        # Ensure we aren't picking up generic job boards like LinkedIn/Indeed by accident
                        if not any(agg in normalized_url for agg in ["linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com"]):
                            is_job_link = True

                if is_job_link and actual_url not in seen_urls:
                    seen_urls.add(actual_url)
                    company = extract_company_from_url(actual_url)
                    
                    unique_str = f"{company}{role}{actual_url}"
                    job_id = hashlib.sha256(unique_str.encode("utf-8")).hexdigest()[:16]
                    
                    found_jobs.append({
                        "job_id": job_id,
                        "title": role, # Default to the searched role
                        "company": company,
                        "location": location or "Remote/Flexible",
                        "apply_link": actual_url,
                        "description": "", # To be scraped later
                        "source": "Google Search",
                        "found_at": datetime.now().isoformat(),
                        "date_posted_str": standardize_date(datetime.now().isoformat()),
                        "status": "pending_scrape",
                        "is_sponsored": False
                    })
                    
        except Exception as e:
            print(f"[WARN] Error executing query '{query}': {e}")
            
    return found_jobs[:max_results]


def fetch_simplify_jobs(job_types: list[str]) -> list[dict]:
    settings = _get_settings()
    blocked_companies = [c.lower()
                         for c in settings.get("blocked_companies", [])]
    blocked_keywords = [k.lower()
                        for k in settings.get("blocked_keywords", [])]

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
            req = urllib.request.Request(
                url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode())

            for item in data:
                # 1. Skip if active=False or is_visible=False
                if not item.get("active", True) or not item.get("is_visible", True):
                    continue

                # 2. Skip if no url/apply link
                apply_link = item.get("url")
                if not apply_link:
                    continue

                # 2b. Skip if job posted before cutoff (hours_old)
                hours_old = settings.get("hours_old", 72)
                cutoff = time.time() - (hours_old * 3600)
                date_posted = item.get(
                    "date_posted") or item.get("date_updated", 0)
                if date_posted and date_posted < cutoff:
                    continue

                # 2c. Category/domain filter
                blocked_cats = settings.get("blocked_categories", [])
                job_category = item.get("category", "")
                if any(blocked.lower() in job_category.lower() for blocked in blocked_cats):
                    continue

                # 2d. Visa/sponsorship filter
                visa_status = settings.get("visa_status", "no_preference")
                sponsorship_raw = item.get("sponsorship") or ""
                is_sponsored = any(
                    s in sponsorship_raw.lower()
                    for s in ["yes", "offers", "will sponsor"]
                )

                if visa_status == "requires_sponsorship":
                    if not is_sponsored:
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
                    job_id = hashlib.sha256(
                        unique_str.encode("utf-8")).hexdigest()[:16]
                else:
                    job_id = str(job_id)

                locations = item.get("locations", [])
                location = locations[0] if locations else "Remote"
                description = item.get("description", "")
                
                date_str = standardize_date(date_posted)

                normalized_jobs.append({
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "location": location,
                    "apply_link": apply_link,
                    "description": description,
                    "source": "simplify",
                    "found_at": datetime.now().isoformat(),
                    "date_posted_str": date_str,  # Added for folder organization
                    "status": "pending_scrape",
                    "is_sponsored": is_sponsored
                })

        except Exception as e:
            print(f"Error fetching from {url}: {e}")

    return normalized_jobs
