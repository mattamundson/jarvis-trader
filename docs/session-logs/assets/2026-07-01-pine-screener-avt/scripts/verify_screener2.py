from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True)

    # Check 1: error banner rendering on /screener after the 501
    page = browser.new_page()
    errs = []
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    page.goto("http://127.0.0.1:3010/screener", wait_until="networkidle", timeout=20000)
    page.get_by_role("button", name="Scan").click()
    page.wait_for_timeout(3000)
    body = page.locator("body").inner_text()
    idx = body.find("501")
    print("=== error text near '501' on /screener ===")
    print(body[max(0,idx-150):idx+150] if idx >= 0 else "(no '501' substring found in visible text)")
    print("=== does page show a red error card? ===")
    print("visible AlertCircle-adjacent error text:", "Scanner error" in body or "error" in body.lower())
    page.close()

    # Check 2: is the hydration mismatch specific to /screener, or repo-wide (pre-existing) on another
    # existing page that also has <input type=number>?
    page2 = browser.new_page()
    hydration_errs = []
    page2.on("console", lambda m: hydration_errs.append(1) if "hydrat" in m.text.lower() else None)
    page2.goto("http://127.0.0.1:3010/watchlist", wait_until="networkidle", timeout=20000)
    page2.wait_for_timeout(1500)
    print("\n=== /watchlist hydration warning count ===", len(hydration_errs))
    page2.close()

    page3 = browser.new_page()
    hydration_errs3 = []
    page3.on("console", lambda m: hydration_errs3.append(1) if "hydrat" in m.text.lower() else None)
    page3.goto("http://127.0.0.1:3010/backtest", wait_until="networkidle", timeout=20000)
    page3.wait_for_timeout(1500)
    print("=== /backtest hydration warning count ===", len(hydration_errs3))
    page3.close()

    browser.close()
