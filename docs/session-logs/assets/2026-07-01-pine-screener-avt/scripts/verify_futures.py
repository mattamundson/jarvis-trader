from playwright.sync_api import sync_playwright
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
hydration = []
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True)
    page = browser.new_page()
    def on_console(msg):
        if msg.type == "error":
            errors.append(msg.text)
            if "hydrat" in msg.text.lower():
                hydration.append(msg.text)
    page.on("console", on_console)

    page.goto("http://127.0.0.1:3010/screener", wait_until="networkidle", timeout=20000)

    # Verify FUT_* codes are present in the Universe dropdown.
    options = page.locator("select").first.locator("option").all_inner_texts()
    print("UNIVERSE OPTIONS:", options)

    # Fill the new Symbols field with real futures tickers (yfinance format) and scan.
    symbols_field = page.get_by_placeholder("e.g. MES=F, MGC=F, GC=F")
    symbols_field.fill("MES=F, MGC=F")
    page.get_by_role("button", name="Scan").click()
    page.wait_for_timeout(40000)

    body = page.locator("body").inner_text()
    idx = body.find("source:")
    print("--- universe_source / counts ---")
    print(body[max(0, idx - 10): idx + 120] if idx >= 0 else "(not found)")

    idx2 = body.find("Focus names")
    print("--- Focus names section ---")
    print(body[idx2: idx2 + 300] if idx2 >= 0 else "(not found)")

    print("HYDRATION WARNINGS:", len(hydration))
    print("ALL CONSOLE ERRORS:", errors)

    page.screenshot(path="/tmp/claude-0/-home-user-jarvis-trader/0ce66359-9106-57e4-81ec-82044b90b6ad/scratchpad/screener_futures.png", full_page=True)
    browser.close()
