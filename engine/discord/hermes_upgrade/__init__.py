"""
Hermes self-improvement loop driven by Discord deep_analyzer signal.

Scans channel 1490851279180660819 bookmark analyses for Hermes-applicable
intelligence (new skills, MCP servers, cron patterns, soul templates,
libraries, config improvements, GEPA targets). Classifies via LLM,
ranks into a backlog, then applies via approval-gated executors per type.

Pipeline:
    deep_analyzer.discord_analyses
        -> scanner.scan_for_candidates()
        -> classifier.classify_batch()
        -> backlog.write_backlog_md()
        -> applier.apply_entry()   # Amo-approved per item
        -> Hermes (skill/MCP/cron/soul/library/config update)
        -> verify + record in applied-log
"""
