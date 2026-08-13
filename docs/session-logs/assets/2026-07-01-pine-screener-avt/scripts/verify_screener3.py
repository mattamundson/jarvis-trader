from playwright.sync_api import sync_playwright
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True)
    page = browser.new_page()
    page.goto("http://127.0.0.1:3010/watchlist", wait_until="networkidle", timeout=20000)
    n = page.locator("input[type=number]").count()
    print("/watchlist <input type=number> count:", n)
    page.close()
    browser.close()
