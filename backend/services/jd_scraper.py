import asyncio
import re
from scrapling.fetchers import StealthyFetcher, DynamicFetcher


# ─── Heading keywords that signal a JD section ──────────────────────────
# When CSS selectors fail (no class/id on the JD container), we search for
# headings whose text matches these patterns and extract from the parent div.
JD_HEADING_KEYWORDS = [
    'job summary', 'job description', 'about the role',
    'about this role', 'about the position', 'about this position',
    'role description', 'position summary', 'position description',
    'the role', 'the opportunity', 'overview',
    'what you will do', "what you'll do", 'responsibilities',
    'essential functions', 'key responsibilities',
    'qualifications', 'requirements', 'what we are looking for',
    "what we're looking for", 'who you are',
]

# ─── Noise selectors to REMOVE before extraction ─────────────────────────
# These elements are stripped from the DOM so broad selectors don't pull in
# navigation links, footers, cookie banners, search widgets, etc.
NOISE_SELECTORS = [
    'nav', 'header', 'footer',
    '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    '.site-header', '.site-footer', '.site-nav',
    '.navbar', '.nav-bar', '.navigation',
    '.footer', '.page-footer', '.global-footer',
    '.header', '.page-header', '.global-header',
    '.sidebar', '.side-bar', 'aside',
    '.cookie-banner', '.cookie-consent', '#cookie-banner',
    '.search-bar', '.search-form', '.job-search',
    '.talent-network', '.sign-up', '.job-alerts',
    '.breadcrumb', '.breadcrumbs',
    '.social-share', '.share-links',
    '.similar-jobs', '.related-jobs', '.recommended-jobs',
    '#onetrust-consent-sdk',       # OneTrust cookie widget
    '.truste_overlay',             # TrustArc overlay
]

# ─── Selectors for common ATS platforms (most specific first) ─────────────
ATS_SELECTORS = [
    # --- Workday ---
    '[data-automation-id="jobPostingDescription"]',
    # --- Greenhouse ---
    '#content .job-post',
    '#content',
    '.job-post',
    # --- Lever ---
    '.section-wrapper.page-full-width',
    '.posting-page',
    # --- Oracle / Taleo / ICIMS ---
    '.job-description',
    '.jd-info',
    '.job-detail',
    '.job-details',
    '.details .description',
    '[class*="jobdescription"]',
    '[class*="jobDescription"]',
    '[class*="job-description"]',
    # --- SmartRecruiters ---
    '.job-sections',
    '.opening-content',
    # --- Jobvite ---
    '.jv-job-detail-description',
    # --- Ashby ---
    '.ashby-job-posting-brief-description',
    # --- Broadbean / generic boards ---
    '.vacancy-description',
    '.job-content',
    '.posting-requirements',
    # --- Broad semantic (only after noise is stripped) ---
    'main',
    'article',
]

# Wait selectors per domain for DynamicFetcher
WAIT_SELECTORS = {
    "myworkdayjobs.com": '[data-automation-id="jobPostingDescription"]',
    "workday.com": '[data-automation-id="jobPostingDescription"]',
    "greenhouse.io": '#content',
    "lever.co": '.section-wrapper',
    "ashbyhq.com": '.job-post',
    "oraclecloud.com": '.details',
    "smartrecruiters.com": '.job-sections',
    "jobvite.com": '.jv-job-detail-description',
    "icims.com": '.iCIMS_InfoMsg_Job',
    "taleo.net": '.job-description',
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
    Extracts cleaned text from a CSS selector on a Scrapling page object.
    Always strips noise elements (nav, header, footer, etc.) from the
    matched element's HTML before extracting text.

    Args:
        page: The Scrapling response object.
        selector (str): CSS selector string.

    Returns:
        str: Cleaned text or empty string if not found/too short.
    """
    try:
        result = page.css(selector)
        if not result:
            return ""
        el = result[0]
        # Get the element's HTML, strip noise, then extract clean text
        raw_html = str(el)
        cleaned = _strip_noise_html(raw_html)
        text = _extract_text_from_html(cleaned)
        if len(text) > 50:
            return text
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


def _strip_noise_html(html: str) -> str:
    """
    Removes common boilerplate HTML elements (nav, header, footer, sidebars,
    cookie banners, etc.) so that broad selectors don't capture page chrome.
    Operates on raw HTML strings via regex to stay dependency-light.
    """
    # Build combined pattern from NOISE_SELECTORS
    # Handle tag selectors  (e.g. 'nav', 'header', 'footer', 'aside')
    tag_names = [s for s in NOISE_SELECTORS if re.fullmatch(r'[a-z]+', s)]
    for tag in tag_names:
        html = re.sub(
            rf'<{tag}[\s>].*?</{tag}>',
            '', html, flags=re.DOTALL | re.IGNORECASE,
        )
    # Handle class selectors  (e.g. '.navbar', '.footer')
    class_names = [s.lstrip('.') for s in NOISE_SELECTORS if s.startswith('.')]
    for cls in class_names:
        # Match any tag whose class attribute contains the given class name
        html = re.sub(
            rf'<([a-z][a-z0-9]*)\b[^>]*class="[^"]*\b{re.escape(cls)}\b[^"]*"[^>]*>.*?</\1>',
            '', html, flags=re.DOTALL | re.IGNORECASE,
        )
    # Handle id selectors  (e.g. '#cookie-banner')
    id_names = [s.lstrip('#') for s in NOISE_SELECTORS if s.startswith('#')]
    for id_val in id_names:
        html = re.sub(
            rf'<([a-z][a-z0-9]*)\b[^>]*id="{re.escape(id_val)}"[^>]*>.*?</\1>',
            '', html, flags=re.DOTALL | re.IGNORECASE,
        )
    # Handle role selectors  (e.g. '[role="navigation"]')
    for sel in NOISE_SELECTORS:
        m = re.match(r'\[role="(.+?)"\]', sel)
        if m:
            role_val = m.group(1)
            html = re.sub(
                rf'<([a-z][a-z0-9]*)\b[^>]*role="{re.escape(role_val)}"[^>]*>.*?</\1>',
                '', html, flags=re.DOTALL | re.IGNORECASE,
            )
    return html


def _extract_body_text(page) -> str:
    """
    Extracts text from the entire page body as a last resort fallback,
    after stripping noise elements.
    """
    if not page.body:
        return ""
    html = page.body.decode(
        "utf-8", errors="ignore") if isinstance(page.body, bytes) else str(page.body)
    html = _strip_noise_html(html)
    return _extract_text_from_html(html)


def _try_heading_heuristic(page) -> str:
    """
    Content-based heuristic for pages where the JD container has no usable
    class or id (e.g. NetApp/Oracle career pages).  Searches for headings
    (h1-h4) whose text matches common JD keywords, then walks up to the
    nearest parent <div> and extracts its full text (noise-stripped).

    Returns:
        str: Extracted JD text, or empty string if nothing matched.
    """
    try:
        for tag in ('h1', 'h2', 'h3', 'h4'):
            headings = page.css(tag)
            if not headings:
                continue
            for heading in headings:
                heading_text = getattr(heading, 'text', '') or ''
                heading_lower = str(heading_text).strip().lower()
                if not any(kw in heading_lower for kw in JD_HEADING_KEYWORDS):
                    continue
                # Walk up to the nearest parent div that contains meaningful content
                parent = heading
                for _ in range(5):  # max 5 levels up
                    p = getattr(parent, 'parent', None)
                    if p is None:
                        break
                    parent = p
                    parent_tag = getattr(parent, 'tag', '') or ''
                    if str(parent_tag).lower() == 'div':
                        # Use HTML-based extraction with noise stripping
                        raw_html = str(parent)
                        cleaned = _strip_noise_html(raw_html)
                        text = _extract_text_from_html(cleaned)
                        if len(text) > 100:
                            return text
    except Exception:
        pass
    return ""


def _extract_from_page(page) -> str:
    """
    Extracts the job description text from a scraped page using a multi-stage
    pipeline.  Every stage strips noise (nav, header, footer, etc.) so
    boilerplate never leaks into the result.

    Pipeline:
      1. ATS-specific CSS selectors (most targeted).
      2. Heading-based heuristic ("Job Summary", "Job Description", etc.).
      3. Body fallback with noise stripped.

    Args:
        page: The Scrapling response object.

    Returns:
        str: Most likely JD text content.
    """
    # 1. Try all ATS selectors (noise is stripped inside _try_css_text)
    for sel in ATS_SELECTORS:
        text = _try_css_text(page, sel)
        if text and len(text) > 100:
            return text

    # 2. Heading heuristic — find headings like "Job Summary" and extract
    #    from their parent container.  Catches pages with no class/id.
    text = _try_heading_heuristic(page)
    if text and len(text) > 100:
        return text

    # 3. Last resort — full body with noise stripped
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
