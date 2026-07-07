# X Bookmarks → OneDrive Export Playbook

Getting your X (Twitter) bookmarks into `OneDrive/jarvis-trader-handoff/bookmarks.html` so Phase 1 of the funnel can ingest them.

X's official API for bookmarks is heavily rate-limited and effectively unusable for bulk export on the free tier. Below are four working approaches ranked from easiest to most complete.

## The Target

The Phase 1 inventory script (`scripts/phase1_inventory.py`) will read EITHER format from your OneDrive folder:

- `OneDrive/jarvis-trader-handoff/bookmarks.html` — an HTML page where each bookmark is an `<a href="https://x.com/...">` link with the tweet text nearby
- `OneDrive/jarvis-trader-handoff/bookmarks.json` — an array of objects like `[{"url": "...", "text": "...", "author": "@handle", "saved_at": "ISO date"}, ...]`

Either works. JSON is cleaner but HTML is easier to produce.

---

## Option 1 — Manual Save-as-HTML (simplest, ~10 minutes for ≤500 bookmarks)

Best when you have a reasonable number of bookmarks and want zero dependencies.

1. Open Chrome/Edge/Firefox and go to https://x.com/i/bookmarks (sign in)
2. **Scroll all the way to the bottom** — X uses infinite scroll, so you have to manually reach the end before saving. For 500+ bookmarks this takes 5–10 minutes of holding `End` or scrolling. Pro tip: open browser DevTools (F12), paste this in the Console, hit Enter, and walk away for a few minutes:
   ```js
   const scroller = setInterval(() => window.scrollBy(0, 5000), 800);
   // To stop early: clearInterval(scroller)
   ```
   Wait until the page stops loading new tweets, then `clearInterval(scroller)` in the console.
3. Once fully scrolled: `Ctrl+S` → **Save as type: "Webpage, Complete"** (or "Webpage, HTML only" — either works)
4. Save it as `bookmarks.html` directly into `C:\Users\matt\OneDrive\jarvis-trader-handoff\` (create the folder if it doesn't exist)
5. Wait for OneDrive to sync (green checkmark on the file)

**Caveats:**
- X re-renders bookmark order on each session — if you don't scroll all the way to the bottom, you'll miss old ones
- The HTML will include a lot of UI chrome, but `phase1_inventory.py` filters for `x.com`/`twitter.com` links and uses the nearby DOM text as the tweet content
- Quote-tweet content and reply context may be truncated

---

## Option 2 — Browser Extension (recommended for >500 bookmarks)

A few extensions still work as of 2026. **[Unverified]** since X's frontend changes break these periodically — check current reviews before installing.

**Reasonably current options (check their store listings yourself before installing):**
- **Twillot** — Chrome extension, exports bookmarks to JSON/CSV
- **Tweet Hunter** — has a bookmarks export feature on its paid plan
- **Black Magic for Twitter** — exports likes and bookmarks

**Procedure (generic, since extension UIs change):**
1. Install the extension from Chrome Web Store
2. Sign into X in your browser
3. Open the extension and trigger "Export Bookmarks" (specific menu varies)
4. Save the resulting JSON or CSV file
5. If it's JSON, rename it to `bookmarks.json` and drop in `OneDrive/jarvis-trader-handoff/`
6. If it's CSV, run this Python one-liner to convert:
   ```powershell
   python -c "import csv, json; rows = list(csv.DictReader(open('bookmarks.csv', encoding='utf-8'))); json.dump([{'url': r.get('url') or r.get('tweet_url'), 'text': r.get('text') or r.get('content'), 'author': r.get('author') or r.get('handle'), 'saved_at': r.get('bookmarked_at') or r.get('created_at')} for r in rows], open(r'C:\Users\matt\OneDrive\jarvis-trader-handoff\bookmarks.json', 'w', encoding='utf-8'), indent=2)"
   ```

**Heads up on privacy:** these extensions can read everything you do on X. Read reviews and prefer extensions with verified developers / many users.

---

## Option 3 — Python script via your existing X OAuth (most controlled, ~30 min setup)

Since you already started the X connector OAuth flow in this conversation, you can use the same token to hit X's `/2/users/me/bookmarks` endpoint directly. **[Unverified]** — Free/Basic tier limits are strict (75 reads per 15 min), but for a one-time export this is fine.

Save this as `export_x_bookmarks.py`:

```python
"""One-time X bookmarks export to JSON. Requires Bearer token from your X developer account."""
import json
import os
import time
import requests

BEARER = os.environ["X_BEARER_TOKEN"]  # set this in PowerShell first
USER_ID = os.environ["X_USER_ID"]      # your numeric X user ID
OUT = r"C:\Users\matt\OneDrive\jarvis-trader-handoff\bookmarks.json"

headers = {"Authorization": f"Bearer {BEARER}"}
url = f"https://api.x.com/2/users/{USER_ID}/bookmarks"
params = {
    "max_results": 100,
    "tweet.fields": "created_at,author_id,text,public_metrics",
    "expansions": "author_id",
    "user.fields": "username,name",
}

all_bookmarks = []
while True:
    r = requests.get(url, headers=headers, params=params, timeout=30)
    if r.status_code == 429:
        print("Rate limited — sleeping 15 min")
        time.sleep(900)
        continue
    r.raise_for_status()
    data = r.json()
    users_by_id = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
    for t in data.get("data", []):
        author = users_by_id.get(t["author_id"], {})
        all_bookmarks.append({
            "url": f"https://x.com/{author.get('username', 'unknown')}/status/{t['id']}",
            "text": t["text"],
            "author": f"@{author.get('username', '')}",
            "saved_at": t.get("created_at"),
        })
    print(f"Fetched {len(all_bookmarks)} so far")
    next_token = data.get("meta", {}).get("next_token")
    if not next_token:
        break
    params["pagination_token"] = next_token

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(all_bookmarks, f, indent=2)
print(f"Saved {len(all_bookmarks)} bookmarks to {OUT}")
```

**Setup:**
1. Get a Bearer Token from the [X Developer Portal](https://developer.x.com) (free tier is fine for one-time use)
2. Find your numeric user ID using [tweeterid.com](https://tweeterid.com) or any "X username to ID" tool
3. In PowerShell:
   ```powershell
   $env:X_BEARER_TOKEN = "your-token"
   $env:X_USER_ID = "your-numeric-id"
   python export_x_bookmarks.py
   ```

---

## Option 4 — Paid bulk tools (only if Options 1–3 fail)

If you have thousands of bookmarks and the above approaches are too painful:
- **[Unverified]** — research before paying. As of mid-2026, some services that export X bookmarks include Twillot Pro, Hookline, and Dewey. Pricing changes constantly and API access fluctuates with Musk's policy changes.
- Whatever you use, request **JSON output** (URL + tweet text + author + date is sufficient).

---

## What to Do After Upload

1. Verify the file is in OneDrive and synced:
   ```powershell
   ls "C:\Users\matt\OneDrive\jarvis-trader-handoff\bookmarks*"
   ```
2. Quick sanity check (optional):
   ```powershell
   # For HTML
   (Get-Content "C:\Users\matt\OneDrive\jarvis-trader-handoff\bookmarks.html" -Raw) -split 'x.com/' | Measure-Object | Select-Object Count
   # For JSON
   python -c "import json; data = json.load(open(r'C:\Users\matt\OneDrive\jarvis-trader-handoff\bookmarks.json', encoding='utf-8')); print(f'{len(data)} bookmarks')"
   ```
3. Re-run Phase 1 — the script auto-detects `bookmarks.html` or `bookmarks.json` in the sync root:
   ```powershell
   $env:JARVIS_FUNNEL_LLM_PROVIDER = "anthropic"
   $env:ANTHROPIC_API_KEY = "sk-ant-..."
   python -m jarvis_funnel.run --phase 1 --repo C:\path\to\jarvis-trader
   ```

---

## What the Inventory Will Do With Your Bookmarks

For each bookmark, Phase 1 will:
1. Filter to trading-relevant content (ES, NQ, VIX, options, strategy keywords, etc.) — non-trading bookmarks are silently dropped
2. Extract `category`, `instrument_class`, `timeframe_class`, claimed metrics (Sharpe, win rate)
3. Try to match it to existing repo strategies (`engine/backtest/run_*.py`):
   - **Auto-merge** if similarity ≥ 0.80 → bookmark and repo code become a single strategy card
   - **Candidate merge** if 0.50–0.80 → flagged for your review in `merge_review.jsonl`
   - **Standalone card** if < 0.50 → becomes a new strategy card with `phase_1_status: NEEDS_IMPLEMENTATION`
4. Any author-suggested variations not in the repo go into the card's `untested_variants_from_bookmarks` field for Phase 3 to test

You don't need to clean the bookmarks first — the script handles noise.

---

## Recommended Path

**For your first run, use Option 1 (manual save-as-HTML).** It's 10 minutes of work, requires no dev account setup, and gets you 90% coverage. If the first inventory pass shows obvious gaps (e.g., missing rich-text content from threads), upgrade to Option 2 or 3 later.
