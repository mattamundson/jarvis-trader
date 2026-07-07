# Cache Filename Contract

> Canonical reference for the IBKR cache filename format used by
> `engine/backtest/export_ibkr_history.py` and consumed by
> `engine/backtest/_gate_v2_helpers.py::_find_latest_cache`.

## Canonical Regex

```
^[A-Z][A-Z0-9]{1,3}_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}_\d{1,2}[hd]\.csv$
```

Defined at:
- **Source of truth:** `engine/backtest/export_ibkr_history.py` — `CACHE_FILENAME_CONTRACT`
- **Assertion path:** `export_ibkr_history._save_merged` — asserts at write-time before saving
- **Test coverage:** `engine/tests/test_cache_filename_contract.py` — 39 tests (commit `9b4add2` + `bc6dc0d`)

## Format

```
<SYMBOL>_<START_DATE>_<END_DATE>_<INTERVAL>.csv
```

| Field | Pattern | Example | Notes |
|-------|---------|---------|-------|
| `SYMBOL` | `[A-Z][A-Z0-9]{1,3}` | `MES`, `MGC`, `M2K` | 2–4 chars; first must be uppercase alpha; remaining may be uppercase alpha or digit |
| `START_DATE` | `\d{4}-\d{2}-\d{2}` | `2024-01-01` | ISO 8601 date |
| `END_DATE` | `\d{4}-\d{2}-\d{2}` | `2026-05-07` | ISO 8601 date; lex sort equivalent to chronological sort |
| `INTERVAL` | `\d{1,2}[hd]` | `1h`, `4h`, `12h`, `1d` | 1–2 digit number + `h` (hours) or `d` (days); `m` (minutes) NOT valid |
| extension | `\.csv` | `.csv` | Always CSV; `.parquet` not allowed |

**Separator:** underscore `_` throughout. No hyphens as field separators.

### Valid Examples

```
MES_2024-01-01_2026-05-07_1h.csv
MGC_2024-04-26_2026-05-07_1h.csv
MNQ_2024-06-01_2026-03-27_4h.csv
MCL_2023-12-31_2026-01-01_1d.csv
M2K_2024-01-01_2026-05-07_1h.csv
MES_2024-01-01_2026-05-07_12h.csv   # two-digit interval
```

### Rejected Examples

| Filename | Reason |
|----------|--------|
| `MES_2024-01-01_1h.csv` | Missing `END_DATE` segment |
| `MES_20240101_2026-05-07_1h.csv` | Non-ISO start date (no hyphens) |
| `MES_2024-01-01_2026-05-07_60m.csv` | `m` not in `[hd]` |
| `mes_2024-01-01_2026-05-07_1h.csv` | Lowercase symbol first char |
| `MESXX_2024-01-01_2026-05-07_1h.csv` | Symbol 5 chars, exceeds max 4 |
| `MES_2024-01-01_2026-05-07_1h.parquet` | Wrong extension |
| `MES-2024-01-01-2026-05-07-1h.csv` | Wrong separator (hyphens) |
| `MES_2024-01-01_2026-05-07_100h.csv` | Three-digit interval exceeds `\d{1,2}` |

## Invariants

1. **`END_DATE > START_DATE`** — enforced semantically; the regex does not verify date ordering, but `_save_merged` uses `df.index.min()` and `df.index.max()` which are monotonic by construction.
2. **Symbol uppercase** — all current tracked symbols are uppercase micro-futures codes (MES, MGC, MNQ, MCL, M2K).
3. **Interval is hours or days** — `h` or `d` suffix only. Minutes-resolution (`m`) is not a valid cache interval.
4. **ISO dates** — `YYYY-MM-DD` only. Any other format (e.g. `YYYYMMDD`, `MM-DD-YYYY`) is rejected.
5. **Future-dated `END_DATE` is structurally valid** — the contract is purely a filename format check; it does not validate that `END_DATE ≤ today`. A file like `MES_2024-01-01_2099-12-31_1h.csv` passes the regex. The selector will pick it as the latest-end-date file if it exists.

## Selector Behavior — `_find_latest_cache`

Location: `engine/backtest/_gate_v2_helpers.py::_find_latest_cache`

```python
def _find_latest_cache(data_dir: Path, prefix: str, suffix: str = "_1h.csv") -> Path:
    ...
```

**Algorithm:**

1. Glob all files matching `<prefix>*<suffix>` in `data_dir`.
2. For each file, extract the end-date segment: `stem.split("_")[2]` (index 2 of underscore-split).
3. Off-contract files with fewer than 3 underscore segments return `""` as end-date key → sort to bottom.
4. Return `max(candidates, key=_end_date)` — lexicographic max on ISO date = chronological max.
5. Raise `FileNotFoundError` if no matching files exist.

**Key property:** A refreshed cache (`MES_2024-01-01_2026-05-07_1h.csv`) always wins over an older copy (`MES_2024-01-01_2026-03-28_1h.csv`) because `"2026-05-07" > "2026-03-28"` lexicographically.

**Off-contract fallback:** If NO conforming file exists, the helper returns the lex-max of whatever is in the glob — it does NOT return `None` or raise for off-contract files. Only an empty glob raises `FileNotFoundError`.

**Suffix filter:** Pass `suffix="_1d.csv"` to select daily-bar files; `suffix="_1h.csv"` (default) for hourly.

## Anti-Patterns (Resolved 2026-05-07)

| Anti-pattern | Why it breaks | Resolution |
|---|---|---|
| Hardcoded primary path in runner | `MES_2024-01-01_2026-03-28_1h.csv` silently used even after cache refresh to `_2026-05-07_` | Use `_find_latest_cache()` — commit `55739db` (MES rank11 + MGC rank4), T09 planned for remaining runners |
| Lowercase symbol in filename | Regex rejects it; `_find_latest_cache` never picks it | Always export with uppercase `SYMBOL` |
| Non-ISO date in filename | Lex sort breaks for non-ISO (e.g. `MES_..._26-05-07_...` sorts before `_2025-...`) | `_save_merged` asserts contract before write |
| Contract-month suffix (`_dec.csv`) | `_dec.csv` ≠ `_1h.csv` suffix filter; file is invisible to selector | Keep filenames ending in `_<N>[hd].csv` only |

## Write-time Assertion

`export_ibkr_history._save_merged` always calls:

```python
if not CACHE_FILENAME_CONTRACT.match(filename):
    raise ValueError(
        f"Cache filename '{filename}' violates the contract ..."
    )
```

This is the canary that catches drift at write-time rather than weeks later when a stale WFO verdict is used. If this assertion fires, the export step is producing a non-compliant filename — investigate the `symbol` or `interval` values being passed to `_save_merged`.

## Related Files

| File | Role |
|------|------|
| `engine/backtest/export_ibkr_history.py` | Defines `CACHE_FILENAME_CONTRACT`; writes cache files; `_save_merged` asserts contract |
| `engine/backtest/_gate_v2_helpers.py` | `_find_latest_cache` — reads cache files; picks by end-date |
| `engine/tests/test_cache_filename_contract.py` | 39 contract + selector tests; covers valid, invalid, and graceful-degradation cases |
| `engine/backtest/cache/` | Canonical cache directory (gitignored; not committed) |

## History

- **Commit `9b4add2`** — Initial `CACHE_FILENAME_CONTRACT` regex + 18 tests
- **Commit `55739db`** — `_find_latest_cache` added to `_gate_v2_helpers`; MES rank11 + MGC rank4 updated to use it (fixing hardcoded-path bug)
- **Commit `bc6dc0d`** — 21 graceful-degradation tests added (malformed filenames, missing date components, future dates, multi-match determinism)
- **T09** (planned) — Roll out `_find_latest_cache` to remaining ~24 runners
