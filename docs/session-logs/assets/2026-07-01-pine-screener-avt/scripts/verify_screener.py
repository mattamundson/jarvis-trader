import sys
from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
console_errors = []
page_errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True)
    page = browser.new_page()
    page.on("console", lambda msg: console_errors.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    page.goto("http://127.0.0.1:3010/screener", wait_until="networkidle", timeout=20000)
    page.screenshot(path="/tmp/claude-0/-home-user-jarvis-trader/0ce66359-9106-57e4-81ec-82044b90b6ad/scratchpad/screener_initial.png", full_page=True)

    title = page.title()
    header_text = page.locator("h1").first.inner_text()
    scan_button = page.get_by_role("button", name="Scan")
    scan_visible = scan_button.is_visible()

    print("PAGE TITLE:", title)
    print("HEADER H1:", header_text)
    print("SCAN BUTTON VISIBLE:", scan_visible)
    print("CONSOLE ERRORS (before click):", console_errors)
    print("PAGE ERRORS (before click):", page_errors)

    scan_button.click()
    page.wait_for_timeout(4000)

    page.screenshot(path="/tmp/claude-0/-home-user-jarvis-trader/0ce66359-9106-57e4-81ec-82044b90b6ad/scratchpad/screener_after_scan.png", full_page=True)

    body_text = page.locator("body").inner_text()
    has_error_banner = "AlertCircle" in body_text or "scan failed" in body_text.lower() or "Scan failed" in body_text
    has_focus_names = "Focus names" in body_text
    has_scanner_status = "scanner" in body_text.lower()

    print("HAS 'Focus names' SECTION:", has_focus_names)
    print("HAS SCANNER-STATUS BADGE TEXT:", has_scanner_status)
    print("CONSOLE ERRORS (after click):", console_errors)
    print("PAGE ERRORS (after click):", page_errors)
    print()
    print("--- relevant body text snippet ---")
    idx = body_text.find("Focus names")
    print(body_text[max(0, idx - 200): idx + 500] if idx >= 0 else body_text[:800])

    browser.close()
