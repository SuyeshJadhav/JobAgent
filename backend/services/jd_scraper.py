import asyncio
import re
from scrapling.fetchers import StealthyFetcher, DynamicFetcher


# ─── Selectors for common ATS platforms ──────────────────────────────────
ATS_SELECTORS = [
    '[data-automation-id="jobPostingDescription"]',   # Workday
    '#content',                                        # Greenhouse
    '.section-wrapper.page-full-width',               # Lever
    '.job-post',                                       # Greenhouse alt
    '.posting-page',                                   # Lever alt
    '.job-description',                                # Generic
    '[class*="jobDescription"]',                       # Generic
    'main',                                            # Semantic
    'article',                                         # Semantic
]

# Wait selectors per domain for DynamicFetcher
WAIT_SELECTORS = {
    "myworkdayjobs.com": '[data-automation-id="jobPostingDescription"]',
    "workday.com": '[data-automation-id="jobPostingDescription"]',
    "greenhouse.io": '#content',
    "lever.co": '.section-wrapper',
    "ashbyhq.com": '.job-post',
    "oraclecloud.com": '.details',
}


def _extract_text_from_html(html: str) -> str:
    """
    Strips HTML tags, styles, and scripts to extract clean text from raw HTML.
    
    Args:
        html (str): The raw HTML input.
        
    Returns:
        str: Sanitized plain text.
    """
    clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
    clean = re.sub(r'<[^>]+>', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _try_css_text(page, selector: str) -> str:
    """
    Attempts to extract text from a specific CSS selector on a Scrapling page object.
    
    Args:
        page: The Scrapling response object.
        selector (str): CSS selector string.
        
    Returns:
        str: Extracted text or empty string if not found/too short.
    """
    try:
        result = page.css(selector)
        if not result:
            return ""
        el = result[0]
        # Try .text attribute first (standard for Scrapling)
        text = getattr(el, 'text', None)
        if text and len(str(text).strip()) > 50:
            return str(text).strip()
        # Fallback to manual tag stripping if .text fails
        raw = getattr(el, 'get', None)
        if callable(raw):
            raw_html = raw()
        elif raw:
            raw_html = str(raw)
        else:
            raw_html = str(el)
        extracted = _extract_text_from_html(raw_html)
        if len(extracted) > 50:
            return extracted
        return ""
    except Exception:
        return ""


def _get_wait_selector(url: str) -> str:
    """
    Determines the best CSS selector to wait for before finishing 
    dynamic rendering, based on the URL domain.
    """
    for domain, selector in WAIT_SELECTORS.items():
        if domain in url:
            return selector
    return "body"


def _extract_body_text(page) -> str:
    """
    Extracts text from the entire page body as a last resort fallback.
    """
    if not page.body:
        return ""
    html = page.body.decode("utf-8", errors="ignore") if isinstance(page.body, bytes) else str(page.body)
    return _extract_text_from_html(html)


def _extract_from_page(page) -> str:
    """
    Iteratively tries multiple ATS-specific selectors to find the most relevant JD text.
    
    Args:
        page: The Scrapling response object.
        
    Returns:
        str: Most likely JD text content.
    """
    for sel in ATS_SELECTORS:
        text = _try_css_text(page, sel)
        if text and len(text) > 100:
            return text
    # Fallback: raw body
    return _extract_body_text(page)


async def scrape_full_jd(url: str) -> str:
    """
    Primary API to scrape a full Job Description from a URL.
    Uses a hybrid strategy:
    1. DynamicFetcher (renders JavaScript) for modern ATS platforms.
    2. StealthyFetcher (static fetch) as a fallback/speed optimization.
    
    Args:
        url (str): The job posting URL.
        
    Returns:
        str: The extracted plain text of the JD, or 'SCRAPE_BLOCKED' if bot-blocked.
    """
    try:
        wait_sel = _get_wait_selector(url)

        # Primary: DynamicFetcher — renders JS, waits for content
        def _fetch_dynamic():
            return DynamicFetcher.fetch(url, headless=True, wait_selector=wait_sel)

        page = await asyncio.to_thread(_fetch_dynamic)
        text = _extract_from_page(page)
        if text and len(text) > 100:
            return text

        # Fallback: StealthyFetcher — faster, works for static pages
        def _fetch_stealth():
            return StealthyFetcher.fetch(url, headless=True)

        page = await asyncio.to_thread(_fetch_stealth)
        text = _extract_from_page(page)
        
        # Check for common bot-blocking strings
        lower_text = text.lower()
        if "enable javascript" in lower_text or "access denied" in lower_text or "cloudflare" in lower_text or "security check" in lower_text:
             print(f"[WARN] Scraper blocked by bot-protection at {url}")
             return f"SCRAPE_BLOCKED"
             
        if text and len(text) > 100:
            return text

        return ""

    except Exception as e:
        print(f"Error scraping JD from {url}: {e}")
        return ""
