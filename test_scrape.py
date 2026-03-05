import asyncio
from scrapling.fetchers import StealthyFetcher, DynamicFetcher
import re

def strip_html(html):
    clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
    clean = re.sub(r'<[^>]+>', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

url = "https://kbr.wd5.myworkdayjobs.com/KBR_Careers/job/Greenbelt-Maryland/SSMO-Software-Engineer-Intern_R2119666"

# Test StealthyFetcher with wait
print("=== StealthyFetcher ===")
page = StealthyFetcher.fetch(url, headless=True)
html = page.body.decode("utf-8", errors="ignore") if isinstance(page.body, bytes) else str(page.body)
text = strip_html(html)
print(f"Body length: {len(html)}")
print(f"Text length: {len(text)}")
print(f"Preview: {text[:300]}")

# Test DynamicFetcher
print("\n=== DynamicFetcher ===")
page2 = DynamicFetcher.fetch(url, headless=True, wait_selector='[data-automation-id="jobPostingDescription"]')
html2 = page2.body.decode("utf-8", errors="ignore") if isinstance(page2.body, bytes) else str(page2.body)
text2 = strip_html(html2)
print(f"Body length: {len(html2)}")
print(f"Text length: {len(text2)}")
print(f"Preview: {text2[:300]}")
