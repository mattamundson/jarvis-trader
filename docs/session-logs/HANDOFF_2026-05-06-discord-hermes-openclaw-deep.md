---
session: 2026-05-06 Discord Pipeline + Hermes/OpenClaw Deep Analysis
branch: feat/tradingview-mcp-gamma-kraken
head: adfb483
status: COMPLETE — pipeline live; Hermes/OpenClaw still blocked
---

## State

| Component | State |
|-----------|-------|
| Engine 8010 | ✅ ok, tv_mcp=true, llm_path=true |
| Jarvis-DiscordAutoImport (15min) | ✅ Active → engine/data/jarvis_trader.db |
| Jarvis-DiscordObsidianSync (02:30) | ✅ Registered, smoke-tested |
| Jarvis-DiscordGitDigest (03:00) | ✅ Registered, smoke-tested |
| CoreyCommentaryProcessor | ✅ data_quality=fresh for today; 5 rows corey_session_bias |
| discord_commentary_fts | ✅ 65,804 rows bootstrapped |
| Hermes | ❌ Needs op signin |
| OpenClaw | ❌ Binary absent from WSL Ubuntu |
| data/jarvis_trader.db (repo root) | ⚠️ 733KB stale artifact — delete with: git rm data/jarvis_trader.db |
| corey_session_bias 2026-05-04/05 | ⚠️ data_quality=none (transient 400 errors) — manual fix: UPDATE SET data_quality='stale' |

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Canonical DB = engine/data/jarvis_trader.db | commentary_processor.py comment explicitly documents prior split-brain 2026-04-10; all scripts now corrected |
| FTS5 as standalone virtual table | Simpler sync semantics than content table; acceptable at ~65K rows |
| MIN_SIGNALS_ANALYSIS = 30 | At n=5, CI = ±40pp (useless); n=30 gives ±18pp first meaningful signal |
| CONVICTION_BUCKET_LOW=0.3 / HIGH=0.6 | Named constants; calibrate after 30 days real data using quantile query in constant comment |
| DCE stdout piped through Write-Host | Without this, PS captures DCE output into function return value — truthy array bypasses $false check |

## Bugs Fixed This Session

1. Em-dash parse errors — replaced all — with -- in 3 PS1 files (PS 5.1 UTF-8 issue)
2. DCE --overwrite removed (deprecated in v2.47.1)
3. Export-Channel stdout capture / P1 hard-fail bypass — Write-Host pipe fix
4. UnicodeEncodeError on ⏰ channel name — encode with errors='replace' before print
5. Split-brain DB — all 3 scripts now point to engine/data/jarvis_trader.db
6. cli.py not passing db_path to CoreyCommentaryProcessor

## Files Changed

- engine/discord/cli.py — unicode fix L114; db_path=args.db L132
- engine/discord/storage.py — FTS5 DDL + triggers + bootstrap; discord_daily_sentiment DDL
- engine/discord/commentary_processor.py — datetime.utcnow() → datetime.now(timezone.utc)
- engine/discord/digest_generator.py — _default_db_path 3-levels (still wrong, see R-I-3); sentiment_label; commentary_health
- engine/discord/mcp_server.py — utcnow fix; FTS5 search with LIKE fallback
- engine/analysis/discord_correlation.py — utcnow fix; MIN_SIGNALS_ANALYSIS=30; chi-squared; constants
- scripts/discord-auto-import.ps1 — all fixes above
- scripts/discord-github-digest.ps1 — db path; em-dashes
- scripts/install-discord-obsidian-sync-task.ps1 — NEW
- scripts/install-discord-digest-task.ps1 — NEW
- [master-jarvis] scripts/discord-obsidian-sync.ps1 — db path; em-dashes

## 13 Improvement Recommendations (see full handoff for code)

- R-I-1: cli.py backfill path doesn't pass db_path
- R-I-2: No FTS5 UPDATE trigger (drift if content updated)
- R-I-3: digest_generator._default_db_path() still wrong (repo root not engine/data)
- R-I-4: mcp_server creates new DB connection per call
- R-I-5: _ensure_cache_table() silent failure obfuscates split-brain bugs
- R-I-6: corey_session_bias DDL in wrong file (processor, not storage)
- R-I-7: FTS5 fallback swallows exceptions silently
- R-I-8: Inline Python in obsidian-sync.ps1 is fragile
- R-I-9: DCE re-downloads all messages every 15 min (no --after filter)
- R-I-10: Hermes_Overnight_Loop_0200 may have missed first fire
- R-I-11: discord_daily_sentiment DDL duplicated in storage.py + sentiment_provider.py
- R-I-12: No alerting when data_quality=none persists
- R-I-13: conviction not normalized/clamped from LLM response

## Hermes Revival

```powershell
op signin
op whoami                                          # verify
pwsh C:\Users\mattm\scripts\start-hermes-gateway.ps1
Invoke-RestMethod http://127.0.0.1:10272/health   # use 127.0.0.1 not localhost
```

NOTE: HERMES_RUNBOOK.md at C:\Users\mattm\scripts\ was confirmed MISSING this session.
Search: Get-ChildItem -Path C:\Users\mattm -Recurse -Filter "HERMES_RUNBOOK*"

## OpenClaw

Binary fully absent from WSL Ubuntu (~/.openclaw, /root/.openclaw, PATH, npm globals).
Investigation path:
1. cat ~/.claude/projects/C--windows-system32/memory/project_openclaw_split_brain.md
2. find ~/.archive -name "openclaw*" (WSL) — may have been binned by home cleanup
3. Check C:\Users\mattm\.openclaw (Windows zombie copy — may have config clues)

## Immediate Next Actions

1. op signin → pwsh ~/scripts/start-hermes-gateway.ps1 (10 min)
2. UPDATE corey_session_bias SET data_quality='stale' WHERE date IN ('2026-05-04','2026-05-05')
3. git rm data/jarvis_trader.db && git commit -m "chore(discord): remove stale root DB"
4. Fix digest_generator._default_db_path() (R-I-3, 5 min)
5. Investigate OpenClaw reinstall (1-2 hr)

## Git Working Tree

unstaged delete: engine/data/gate_v2_verdicts/MNQ_orb_rank1.json
untracked: engine/backtest/run_mgc_trend_rank3.py
untracked: engine/data/gate_v2_verdicts/MGC_trend_rank3.json

Full deep handoff: ~/.claude/handoffs/HANDOFF_2026-05-06_discord-pipeline-hermes-openclaw.md
