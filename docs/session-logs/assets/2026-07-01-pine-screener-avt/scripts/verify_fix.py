from playwright.sync_api import sync_playwright
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
hydration_msgs = []
all_errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True)
    page = browser.new_page()
    def on_console(msg):
        if msg.type == "error":
            all_errors.append(msg.text)
            if "hydrat" in msg.text.lower():
                hydration_msgs.append(msg.text)
    page.on("console", on_console)
    page.goto("http://127.0.0.1:3010/screener", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(1500)
    print("HYDRATION WARNINGS:", len(hydration_msgs))
    print("TOTAL CONSOLE ERRORS:", len(all_errors))
    for e in all_errors:
        print(" -", e[:150])
    # Functional check: type into an input, confirm value updates (text input still works like before)
    inp = page.locator('input[placeholder="off"]')  # MM min field
    inp.fill("5")
    val = inp.input_value()
    print("MM min field after typing '5':", val)
    page.screenshot(path="/tmp/claude-0/-home-user-jarvis-trader/0ce66359-9106-57e4-81ec-82044b90b6ad/scratchpad/screener_fixed.png", full_page=True)
    browser.close()
