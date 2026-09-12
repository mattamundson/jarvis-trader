# MES Deep-Cache Provenance — 2026-09-12

Scope: research-only provenance sidecar; no live engine, risk, kill-switch, broker, `.env`, `paper_config.py`, or symbol-gate changes.

## Active cache identity
- Path: `C:\Users\mattm\ThinkorSwim\jarvis-dm-edge-screen-20260911\engine\backtest\cache\MES_2019-05-05_2026-08-26_1h.csv`
- SHA256: `e26631c012b128284e61526dad78e7d39a3c180634dad7398a7dd8cc225f83fe`
- Bytes: `3859723`
- Rows: `43010`
- Header: `timestamp,rtype,publisher_id,instrument_id,open,high,low,close,volume,symbol`
- First timestamp: `2019-05-05 22:00:00+00:00`
- Last timestamp: `2026-08-26 20:00:00+00:00`
- Real span: `7.309984` years

## Data-quality checks
| Check | Result |
|---|---:|
| Duplicate timestamps | 0 |
| Timestamp parse-bad rows | 0 |
| Timestamp monotonic violations | 0 |
| Blank fields | 1720 |
| NaN/null tokens | 0 |
| Invalid numeric fields | 0 |
| OHLC invariant violations | 0 |
| Negative volume rows | 0 |

## Interval profile
- Min delta seconds: `3600.0`
- Max delta seconds: `277200.0`
- Top delta counts: `[('3600', 41120), ('7200', 1449), ('180000', 314), ('21600', 45), ('205200', 31), ('266400', 10), ('176400', 7), ('183600', 7), ('190800', 7), ('18000', 4)]`

## Archive cross-checks
| File | Exists | Rows | First timestamp | Last timestamp | SHA256 |
|---|---:|---:|---|---|---|
| `C:\Users\mattm\Archive\2026\ci-cache-cleanup\MES_2019-05-05_2026-08-23_1h.csv` | True | 42942 | `2019-05-05 22:00:00+00:00` | `2026-08-23 22:00:00+00:00` | `327c595e527865ba90958cf1beae996e647e5f2c33809dcd5c9425cd34161721` |
| `C:\Users\mattm\Archive\2026\ci-cache-cleanup\MES_2015-01-01_2026-08-16_1h.csv` | True | 42826 | `2019-05-05 22:00:00+00:00` | `2026-08-14 20:00:00+00:00` | `f3156a3c5befe274c8fd0f99eb8fc90449745f65895c7d91bb8b16c7cfa46762` |

## Lineage verdict
The active cache is the selected source because it has the latest verified endpoint and highest row count among discovered local/archived MES 1h caches. The archived `MES_2015-01-01_2026-08-16_1h.csv` name is misleading for statistical coverage: its first real timestamp is `2019-05-05 22:00:00+00:00`, so the usable history begins in 2019, not 2015.

## Statistical-use boundary
This sidecar improves reproducibility of PR #814 research artifacts only. It does **not** certify runtime promotion. `60/200/2.0` remains the best point estimate, but paired DM, date-aligned DM, PBO, and DSR evidence did not establish statistically certified superiority.

## Machine-readable artifact
- Repo: `engine/data/gate_v2_verdicts/MES_DEEP_CACHE_PROVENANCE_2026-09-12.json`
- Vault report: `C:/Users/mattm/master-jarvis/second-brain/reports/MES_DEEP_CACHE_PROVENANCE_2026-09-12.json`
