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
    Checks if the job location is within the US.
    Returns False if it hits the blocklist.
    Returns True if it hits the allowlist or if uncertain (fallback).
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
        
    # 3. Allowlist (Pass Fast) - US State Codes (CASE SENSITIVE to avoid "in", "me", "or" false positives)
    state_pattern = re.compile(r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b")
    if state_pattern.search(location_str):
        return True
        
    # 4. Fallback: Assume True and let LLM/Dealbreakers handle it
    return True


def contains_bad_title(title: str) -> str | None:
    """Check if the job title contains any BAD_TITLES match."""
    if not title:
        return None
    title_lower = title.lower()
    for bad in BAD_TITLES:
        if bad in title_lower:
            return bad
    return None

def contains_dealbreakers(text: str) -> str | None:
    """Check if the job description contains any DEALBREAKER_TERMS."""
    if not text:
        return None
    text_lower = text.lower()
    for db in DEALBREAKER_TERMS:
        if db in text_lower:
            return db
    return None

def is_auto_shortlist_title(title: str) -> bool:
    """Check if the title strictly contains perfect match roles we NEVER want to reject."""
    if not title:
        return False
    title_lower = title.lower()
    return any(good in title_lower for good in AUTO_SHORTLIST_TITLES)

def trim_jd_text(raw_text: str) -> str:
    """
    Cleans and truncates a raw Job Description using fuzzy signature matching
    to remove boilerplate at the bottom.
    """
    if not raw_text:
        return ""

    # Clean up whitespace: replace multiple newlines with \n\n, and compress spaces
    text = re.sub(r'\n{3,}', '\n\n', raw_text)
    text = re.sub(r' +', ' ', text).strip()
    
    # Track the current length for positional logic
    current_len = len(text)
    if current_len == 0:
        return ""

    # 1. The EEO Signature Chop
    # Find EEO legal boilerplate (only effective if in the bottom 40% of the text)
    eeo_pattern = re.compile(
        r"(?i)(equal opportunity employer|without regard to race|race, color, religion|sexual orientation|gender identity|national origin)"
    )
    eeo_match = eeo_pattern.search(text)
    if eeo_match:
        idx = eeo_match.start()
        # Bottom 40% means the index must be greater than or equal to 60% (0.6) of the total length
        if idx >= current_len * 0.60:
            text = text[:idx].strip()
            # Update the length for the next chop check
            current_len = len(text)

    # 2. The Benefits/Footer Chop
    # Find common footer/benefits signals (only effective if in the bottom 30% of the text)
    benefits_pattern = re.compile(
        r"(?i)(what we offer\b|perks and benefits\b|comprehensive benefits\b|401\(k\).*match|medical, dental, and vision|how to apply\b|about the company\b)"
    )
    benefits_match = benefits_pattern.search(text)
    if benefits_match:
        idx = benefits_match.start()
        # Bottom 30% means the index must be greater than or equal to 70% (0.7) of the total length
        if idx >= current_len * 0.70:
            text = text[:idx].strip()

    return text
