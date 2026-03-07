import re

BAD_TITLES = ["marketing", "sales", "hr", "finance", "mechanical", "electrical", "frontend", "ui/ux"]
DEALBREAKER_TERMS = ["clearance", "ts/sci", "ph.d", "phd"]
AUTO_SHORTLIST_TITLES = ["software engineer intern", "swe intern", "software development intern", "ai intern", "machine learning intern"]

NON_US_LOCATIONS = [
    "uk", "united kingdom", "london", "canada", "toronto", "vancouver", 
    "india", "australia", "berlin", "amsterdam", "paris"
]

def is_target_location(location_str: str) -> bool:
    """
    Checks if a job location is within the target geographic area (US).
    
    Args:
        location_str (str): The raw location string (e.g., 'San Francisco, CA' or 'London').
        
    Returns:
        bool: True if US or uncertain, False if explicitly non-US.
    """
    if not location_str:
        return True

    loc_lower = location_str.lower()
    
    # 1. Blocklist (Fail Fast)
    for bad_loc in NON_US_LOCATIONS:
        if bad_loc in loc_lower:
            return False
            
    # 2. Allowlist (Pass Fast) - Explicit US indicators
    if "us" in loc_lower or "usa" in loc_lower or "united states" in loc_lower:
        return True
        
    # 3. Allowlist (Pass Fast) - US State Codes (CASE SENSITIVE)
    state_pattern = re.compile(r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b")
    if state_pattern.search(location_str):
        return True
        
    # 4. Fallback: Assume True and let LLM/Dealbreakers handle it
    return True


def contains_bad_title(title: str) -> str | None:
    """
    Checks if the job title contains any forbidden keywords (e.g. 'Marketing', 'Sales').
    
    Args:
        title (str): Job title.
        
    Returns:
        str | None: The matched forbidden keyword if found, else None.
    """
    if not title:
        return None
    title_lower = title.lower()
    for bad in BAD_TITLES:
        if bad in title_lower:
            return bad
    return None

def contains_dealbreakers(text: str) -> str | None:
    """
    Scans full JD text for structural dealbreakers (e.g. 'Security Clearance', 'PhD required').
    
    Args:
        text (str): Job description text.
        
    Returns:
        str | None: The matched dealbreaker term if found, else None.
    """
    if not text:
        return None
    text_lower = text.lower()
    for db in DEALBREAKER_TERMS:
        if db in text_lower:
            return db
    return None

def is_auto_shortlist_title(title: str) -> bool:
    """
    Checks if the title is a high-priority match (e.g. 'SWE Intern') 
    that should bypass certain score deductions.
    
    Args:
        title (str): Job title.
        
    Returns:
        bool: True if it's a VIP title.
    """
    if not title:
        return False
    title_lower = title.lower()
    return any(good in title_lower for good in AUTO_SHORTLIST_TITLES)

def trim_jd_text(raw_text: str) -> str:
    """
    Cleans and truncates a raw Job Description to remove boilerplate (EEO, Benefits, Footer).
    Uses fuzzy signature matching to find logical splits in the bottom half of the text.
    
    Args:
        raw_text (str): The raw text extracted from a job posting website.
        
    Returns:
        str: Cleaned and trimmed text.
    """
    if not raw_text:
        return ""

    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', raw_text)
    text = re.sub(r' +', ' ', text).strip()
    
    current_len = len(text)
    if current_len == 0:
        return ""

    # 1. The EEO Signature Chop: Chop off legal boilerplate if found in bottom 40%
    eeo_pattern = re.compile(
        r"(?i)(equal opportunity employer|without regard to race|race, color, religion|sexual orientation|gender identity|national origin)"
    )
    eeo_match = eeo_pattern.search(text)
    if eeo_match:
        idx = eeo_match.start()
        if idx >= current_len * 0.60:
            text = text[:idx].strip()
            current_len = len(text)

    # 2. The Benefits/Footer Chop: Chop off benefits/footer if found in bottom 30%
    benefits_pattern = re.compile(
        r"(?i)(what we offer\b|perks and benefits\b|comprehensive benefits\b|401\(k\).*match|medical, dental, and vision|how to apply\b|about the company\b)"
    )
    benefits_match = benefits_pattern.search(text)
    if benefits_match:
        idx = benefits_match.start()
        if idx >= current_len * 0.70:
            text = text[:idx].strip()

    return text

def safe_filename(name: str) -> str:
    """
    Converts a string (Company/Title) into a filesystem-safe format.
    Removes special characters and replaces spaces with underscores.
    
    Args:
        name (str): The input string.
        
    Returns:
        str: A safe filename string.
    """
    val = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', str(name))
    return re.sub(r'_+', '_', val).strip('_')
