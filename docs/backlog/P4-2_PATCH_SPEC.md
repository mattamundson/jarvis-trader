# P4-2 Patch Spec — dashboard-guard `build_integrity()` served-vs-on-disk parity

**Status:** BLOCKED — designed, not applied. See reason below.

## Why this is a spec, not a commit

Task instructions said the target file was "likely `C:\Users\mattm\scripts\check.py` or
similar" in the `home-scripts` repo that P4-1 found dirty (10 modified + 11 untracked, main
22 ahead of origin/main) and correctly refused to commit into.

The actual file is **not** in that repo. It is:

```
C:\Users\mattm\.claude\loops\dashboard-guard\check.py
```

`C:\Users\mattm\.claude` is itself a separate git repo (`origin` =
`github.com/mattamundson/claude-config-backup.git`), and it is **far dirtier** than the
`home-scripts` repo P4-1 found:

- `git status --porcelain` in `C:\Users\mattm\.claude` returns **699** changed paths.
- `loops/dashboard-guard/` (the entire directory containing `check.py`, `run.ps1`,
  `report-latest.md`, `heal-state.json`, `.heartbeat`) is **untracked** (`??`) in that repo —
  it has never been committed at all.
- `HEAD` is 20 commits ahead of `origin/main` (0 behind).

Committing here would mean either (a) committing a working file that was never under version
control, inside a 699-file-dirty tree, with no way to isolate "my change" from everything
else already sitting uncommitted, or (b) leaving it uncommitted, which achieves nothing a
plain edit wouldn't. Per the same protocol P4-1 used ("never commit into a dirty shared
repo — that's the exact mistake this protocol exists to prevent"), this task stops here
instead. Amo should triage the `~/.claude` working tree (both this and the `home-scripts`
tree P4-1 flagged) before either P4-1 or P4-2 can land for real.

## The fix

Extend `build_integrity()` in `check.py` (currently lines 51–105) with two new checks run
immediately after the existing CSS-bundle probe (after the `return out` guard at line 90,
before the final CSS fetch/return at lines 92–105 — i.e. insert as checks **F** and **G**,
appended to the same `out: list[str]` before the function returns). Add `import re` to the
top-of-file import block (after `import json`, alphabetical: `json`, `re`, `subprocess`,
`sys`, `time`, `urllib.request`).

### New code (append inside `build_integrity()`, after the existing CSS-bundle try/except
block, before `return out`)

```python
    # Check F/G: served-vs-on-disk parity. The existing checks above test that
    # SOME 200 comes back for the HTML and for one on-disk CSS filename -- but a
    # rebuild-without-restart leaves a stale server happily serving the OLD
    # bundle's HTML (which references the OLD hashed filenames, which still
    # exist on disk) while the NEW on-disk build sits unserved. Every prior
    # check goes green in that state. Close it by fetching the live page and
    # cross-checking every asset URL it actually references, plus the buildId
    # baked into that HTML, against what's on disk right now.
    try:
        with urllib.request.urlopen(URL, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        out.append(f"NOTIFY: could not fetch {URL} for served-vs-disk parity check "
                   f"({exc.__class__.__name__}: {exc}) -- skipping checks F/G.")
        return out

    # Check F: every /_next/static/** URL referenced in the served HTML must 200.
    asset_paths = sorted(set(re.findall(r'/_next/static/[^"\'\s)]+', html)))
    dead_assets: list[str] = []
    for path in asset_paths:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method="HEAD")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    dead_assets.append(f"{path} -> HTTP {resp.status}")
        except Exception as exc:
            dead_assets.append(f"{path} -> {exc.__class__.__name__}: {exc}")
    if dead_assets:
        sample = "; ".join(dead_assets[:5])
        more = f" (+{len(dead_assets) - 5} more)" if len(dead_assets) > 5 else ""
        out.append(f"NOTIFY: served HTML references {len(dead_assets)} asset(s) that do "
                   f"NOT 200: {sample}{more} -- the served page and the on-disk build have "
                   f"diverged (classic rebuild-without-restart). pm2 restart {PM2_APP} "
                   "(report only -- this check does not restart automatically).")

    # Check G: served buildId (from __NEXT_DATA__, or the /_next/static/<id>/
    # path segment used by _buildManifest.js etc as a fallback) must match
    # .next/BUILD_ID on disk. A mismatch means pm2 is still serving an OLDER
    # build than what's on disk -- needs a restart, not a rebuild.
    served_build_id = None
    m = re.search(r'"buildId":"([^"]+)"', html)
    if m:
        served_build_id = m.group(1)
    else:
        for path in asset_paths:
            m2 = re.match(r"/_next/static/([^/]+)/", path)
            if m2 and m2.group(1) != "chunks":
                served_build_id = m2.group(1)
                break

    disk_build_id = bid  # already read earlier in this function (line 74)
    if served_build_id and disk_build_id and served_build_id != disk_build_id:
        out.append(f"NOTIFY: served buildId ({served_build_id}) != on-disk BUILD_ID "
                   f"({disk_build_id}) -- pm2 '{PM2_APP}' is serving a stale build. "
                   f"pm2 restart {PM2_APP} (report only -- this check does not restart "
                   "automatically).")
    elif served_build_id is None:
        out.append("NOTIFY: could not extract a served buildId from the live HTML "
                   "(neither __NEXT_DATA__ nor a /_next/static/<id>/ path matched) -- "
                   "served-vs-disk buildId parity could not be verified this run.")
```

### Notes on correctness / design choices

- **HEAD not GET** for the asset-existence probe (check F) to avoid downloading full JS/CSS
  bundles every guard cycle — dashboard-guard fires frequently (loop cadence), and this stays
  cheap. `urlopen` with a `HEAD` `Request` is stdlib-only, consistent with the rest of the
  file's dependency-free style.
- **`disk_build_id` reuses `bid`**, the variable already computed earlier in the existing
  function body (current line 74: `bid = build_id.read_text().strip() if build_id.is_file()
  else ""`) — no new disk read needed.
- **Report-only, never mutates.** Neither new check calls `pm2 restart` or any subprocess —
  they only append `NOTIFY:` strings to the `out` list, exactly like every existing check in
  this function. The only place `check.py` ever calls `pm2 restart` is the pre-existing
  self-heal branch in `main()` (lines 178–201), gated on "site DOWN AND port free" — this
  patch does not touch that branch or its gating condition, so served-vs-disk mismatches
  detected here can NEVER trigger a restart on their own, per the task requirement.
- **buildId extraction has two fallbacks** because Next.js App Router pages don't always
  serialize `__NEXT_DATA__` the way Pages Router does; the `/_next/static/<buildId>/...`
  path segment (used by `_buildManifest.js`, `_ssgManifest.js`, etc.) is the more reliable
  signal in App Router and is tried second. If neither is present the check reports
  "could not verify" rather than silently passing (fail-loud, not fail-open, matching this
  file's existing philosophy of "never green on error" — see `main()`'s top-level
  `except Exception` at line 240).
- **No new imports beyond `re`** (stdlib, already implicitly available; not currently
  imported in this file).

## Verification plan (once repo cleanliness allows a real commit)

1. `python C:\Users\mattm\.claude\loops\dashboard-guard\check.py` against the live dashboard
   (port 3010) in its current healthy state — expect exit 0, no new NOTIFY lines.
2. Deliberate repro (per the plan doc's own suggested verification: "~1 min of live bad
   state — do it outside trading hours"): touch/rename one file under
   `dashboard/.next/static/` (or run `pnpm build` without a `pm2 restart` after, so the
   server keeps serving cached old asset paths that no longer exist on disk) and re-run
   `check.py` — expect a Check F or G NOTIFY line, exit 2, and confirm `pm2 jlist` shows no
   restart occurred as a side effect of running the checker.
3. Restore state, re-run, confirm back to exit 0.

## Files touched by this spec (once applied)

- `C:\Users\mattm\.claude\loops\dashboard-guard\check.py` — add `import re`; extend
  `build_integrity()` with checks F and G as above.
