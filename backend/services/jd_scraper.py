import asyncio
import re
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

_browser = None
_playwright = None

async def _get_browser():
    global _browser, _playwright
    if _browser is None:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
    return _browser

async def scrape_full_jd(url: str) -> str:
    try:
        browser = await _get_browser()
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except PlaywrightTimeoutError:
            print(f"Timeout loading {url}, proceeding to extract text anyway.")
        except Exception as e:
            print(f"Error loading {url}: {e}")
            
        inner_text = await page.evaluate("document.body.innerText")
        await context.close()
        
        if inner_text:
            cleaned_text = re.sub(r'\n{3,}', '\n\n', inner_text)
            cleaned_text = cleaned_text.strip()
            return cleaned_text
        return ""
    except Exception as e:
        print(f"Error scraping JD from {url}: {e}")
        return ""
