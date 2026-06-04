"""
engine.journal.builder — data-pulling + Markdown-rendering logic for the daily trading journal.

All DB access is read-only (SELECT only). No writes to any source table.

Public functions:
    build_journal_entry(date, db_path, log_path=None) -> dict
    render_markdown(entry: dict) -> str
    write_to_vault(entry: dict, vault_root: str) -> Path
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

JournalEntry = dict[str, Any]

# ---------------------------------------------------------------------------
# DB helpers — read-only
# ---------------------------------------------------------------------------


def _connect_ro(db_path: str) -> sqlite3.Connection:
    """Open a read-only SQLite connection (URI mode)."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------


def _fetch_trades(conn: sqlite3.Connection, target_date: date) -> list[dict]:
    """Closed paper trades whose exit_time falls on target_date (UTC)."""
    date_str = target_date.isoformat()
    cursor = conn.execute(
        """
        SELECT
            trade_id,
            symbol,
            side,
            quantity,
            entry_price,
            exit_price,
            entry_time,
            exit_time,
            pnl,
            regime,
            strategy_params
        FROM paper_trades
        WHERE status = 'closed'
          AND date(exit_time) = ?
        ORDER BY exit_time
        """,
        (date_str,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_pnl_snapshot(conn: sqlite3.Connection, target_date: date) -> dict | None:
    """Most recent pnl_snapshots row for target_date."""
    date_str = target_date.isoformat()
    cursor = conn.execute(
        """
        SELECT daily_pnl, portfolio_equity, peak_equity, consecutive_losses
        FROM pnl_snapshots
        WHERE date = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (date_str,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _fetch_commentary(conn: sqlite3.Connection, target_date: date, top_n: int = 5) -> list[dict]:
    """Top N substantive Corey messages (>= 200 chars) by content length."""
    date_str = target_date.isoformat()
    cursor = conn.execute(
        """
        SELECT message_id, timestamp, content, channel
        FROM discord_corey_commentary
        WHERE date(timestamp) = ?
          AND length(content) >= 200
        ORDER BY length(content) DESC
        LIMIT ?
        """,
        (date_str, top_n),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_bot_signal_summary(conn: sqlite3.Connection, target_date: date) -> list[dict]:
    """Count of bot signals grouped by symbol and direction for target_date."""
    date_str = target_date.isoformat()
    cursor = conn.execute(
        """
        SELECT symbol, direction, COUNT(*) AS signal_count
        FROM discord_bot_signals
        WHERE date(timestamp) = ?
        GROUP BY symbol, direction
        ORDER BY signal_count DESC
        """,
        (date_str,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _fetch_kill_switch_events(conn: sqlite3.Connection, target_date: date) -> list[dict]:
    """
    Kill-switch events on target_date.

    Primary source: system_state table (current state only — captures the snapshot).
    We also look at alert_log for KILL_SWITCH alert_type on the target date.
    """
    date_str = target_date.isoformat()
    events: list[dict] = []

    # Check alert_log for kill switch alerts
    try:
        cursor = conn.execute(
            """
            SELECT alert_type, symbol, message, status, created_at
            FROM alert_log
            WHERE alert_type LIKE '%kill%switch%'
               OR alert_type LIKE '%KILL%'
               OR message LIKE '%kill switch%'
               OR message LIKE '%KILL SWITCH%'
            ORDER BY created_at
            """,
        )
        for row in cursor.fetchall():
            row_dict = dict(row)
            created_at = row_dict.get("created_at", "") or ""
            if created_at.startswith(date_str):
                events.append(row_dict)
    except sqlite3.OperationalError:
        pass

    # Check system_state — if kill_switch_active was updated on this date
    try:
        cursor = conn.execute(
            """
            SELECT key, value, updated_at
            FROM system_state
            WHERE key IN ('kill_switch_active', 'kill_switch_reason')
            """,
        )
        for row in cursor.fetchall():
            row_dict = dict(row)
            updated = row_dict.get("updated_at", "") or ""
            if updated.startswith(date_str) and row_dict.get("value") == "true":
                events.append(
                    {
                        "alert_type": "kill_switch_state",
                        "message": f"Kill switch active: {row_dict.get('value')}",
                        "created_at": updated,
                    }
                )
    except sqlite3.OperationalError:
        pass

    return events


# ---------------------------------------------------------------------------
# jarvis_ask.log parser
# ---------------------------------------------------------------------------


def _parse_ask_log(log_path: Path, target_date: date) -> dict[str, Any]:
    """
    Parse JSONL jarvis_ask.log and return an intent histogram for target_date.

    Returns:
        {
            "total_queries": int,
            "intent_counts": dict[str, int],  # sorted by count desc
        }
    """
    if log_path is None or not log_path.exists():
        return {"total_queries": 0, "intent_counts": {}}

    date_prefix = target_date.isoformat()
    intent_counter: Counter[str] = Counter()

    with log_path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("Line %d: JSON parse error in jarvis_ask.log", lineno)
                continue

            ts = rec.get("timestamp", "") or ""
            # Fast prefix check first
            if not str(ts).startswith(date_prefix):
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if dt.astimezone(timezone.utc).date() != target_date:
                        continue
                except (ValueError, TypeError):
                    continue

            intent = str(rec.get("intent", "unknown")).strip() or "unknown"
            intent_counter[intent] += 1

    total = sum(intent_counter.values())
    return {
        "total_queries": total,
        "intent_counts": dict(intent_counter.most_common()),
    }


# ---------------------------------------------------------------------------
# build_journal_entry
# ---------------------------------------------------------------------------


def build_journal_entry(
    target_date: date,
    db_path: str,
    log_path: str | None = None,
) -> JournalEntry:
    """
    Pull all data for target_date and return a structured entry dict.

    Args:
        target_date: The date to generate the journal for.
        db_path: Absolute path to jarvis_trader.db.
        log_path: Optional path to jarvis_ask.log.

    Returns:
        {
            "frontmatter": dict,
            "trades": list[dict],
            "pnl_snapshot": dict | None,
            "commentary": list[dict],
            "bot_signals": list[dict],
            "jarvis_asks": dict,
            "kill_switch_events": list[dict],
            "generated_at": str (ISO UTC),
        }
    """
    conn = _connect_ro(db_path)
    try:
        trades = _fetch_trades(conn, target_date)
        pnl_snap = _fetch_pnl_snapshot(conn, target_date)
        commentary = _fetch_commentary(conn, target_date)
        bot_signals = _fetch_bot_signal_summary(conn, target_date)
        kill_events = _fetch_kill_switch_events(conn, target_date)
    finally:
        conn.close()

    # jarvis_ask.log
    lp = Path(log_path) if log_path else None
    jarvis_asks = _parse_ask_log(lp, target_date)

    # Compute frontmatter fields
    trade_count = len(trades)
    wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
    win_rate = round(wins / trade_count, 4) if trade_count > 0 else None
    daily_pnl = pnl_snap["daily_pnl"] if pnl_snap else None

    frontmatter: dict[str, Any] = {
        "source": "trading-journal",
        "kind": "daily-journal",
        "date": target_date.isoformat(),
        "trade_count": trade_count,
        "daily_pnl_usd": daily_pnl,
        "win_rate": win_rate,
        "tags": [
            "trading-journal",
            "daily",
            "jarvis-trader/audit-trail",
        ],
    }

    return {
        "frontmatter": frontmatter,
        "trades": trades,
        "pnl_snapshot": pnl_snap,
        "commentary": commentary,
        "bot_signals": bot_signals,
        "jarvis_asks": jarvis_asks,
        "kill_switch_events": kill_events,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


def _yaml_value(v: Any) -> str:
    """Format a Python value as a YAML scalar (minimal quoting)."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace('"', '\\"')
    return f'"{s}"'


def _render_frontmatter(fm: dict) -> str:
    lines = ["---"]
    for key, val in fm.items():
        if key == "tags":
            lines.append("tags:")
            for tag in val:
                lines.append(f"  - {tag}")
        else:
            lines.append(f"{key}: {_yaml_value(val)}")
    lines.append("---")
    return "\n".join(lines)


def _render_trades_table(trades: list[dict]) -> str:
    if not trades:
        return "_No closed trades on this date._"
    header = "| Symbol | Side | Qty | Entry | Exit | P&L | Regime |"
    sep = "|--------|------|-----|------:|-----:|----:|--------|"
    rows = [header, sep]
    for t in trades:
        pnl = t.get("pnl") or 0.0
        pnl_str = f"${pnl:+.2f}"
        rows.append(
            f"| {t.get('symbol','?')} "
            f"| {(t.get('side') or '?').upper()} "
            f"| {t.get('quantity') or ''} "
            f"| {t.get('entry_price') or ''} "
            f"| {t.get('exit_price') or ''} "
            f"| {pnl_str} "
            f"| {t.get('regime') or '—'} |"
        )
    return "\n".join(rows)


def _render_pnl_summary(pnl_snap: dict | None) -> str:
    if not pnl_snap:
        return "_No P&L snapshot for this date._"
    daily = pnl_snap.get("daily_pnl")
    equity = pnl_snap.get("portfolio_equity")
    peak = pnl_snap.get("peak_equity")
    consec = pnl_snap.get("consecutive_losses")
    dd_pct = None
    if equity is not None and peak and peak > 0:
        dd_pct = round((peak - equity) / peak * 100, 2)

    lines = []
    if daily is not None:
        lines.append(f"- **Daily P&L:** ${daily:+.2f}")
    if equity is not None:
        lines.append(f"- **Portfolio equity:** ${equity:,.2f}")
    if peak is not None:
        lines.append(f"- **Equity peak:** ${peak:,.2f}")
    if dd_pct is not None:
        lines.append(f"- **Drawdown from peak:** {dd_pct:.2f}%")
    if consec is not None:
        lines.append(f"- **Consecutive losses:** {consec}")
    return "\n".join(lines) if lines else "_No data._"


def _render_commentary(commentary: list[dict]) -> str:
    if not commentary:
        return "_No substantive Corey commentary (>=200 chars) on this date._"
    parts = []
    for msg in commentary:
        ts = msg.get("timestamp", "")
        channel = msg.get("channel", "")
        content = (msg.get("content") or "").strip()
        header = f"> **{ts}** — #{channel}" if channel else f"> **{ts}**"
        # Wrap content as blockquote
        quoted = "\n".join(f"> {line}" for line in content.splitlines())
        parts.append(f"{header}\n{quoted}")
    return "\n\n".join(parts)


def _render_bot_signals(signals: list[dict]) -> str:
    if not signals:
        return "_No bot signals on this date._"
    header = "| Symbol | Direction | Count |"
    sep = "|--------|-----------|------:|"
    rows = [header, sep]
    for s in signals:
        rows.append(
            f"| {s.get('symbol','?')} "
            f"| {(s.get('direction') or '—').upper()} "
            f"| {s.get('signal_count', 0)} |"
        )
    return "\n".join(rows)


def _render_jarvis_asks(asks: dict) -> str:
    total = asks.get("total_queries", 0)
    intent_counts = asks.get("intent_counts", {})
    if total == 0:
        return "_No /jarvis/ask requests recorded on this date._"

    header = "| Intent | Count | Share |"
    sep = "|--------|------:|------:|"
    rows = [header, sep]
    for intent, count in intent_counts.items():
        share = f"{count / total * 100:.1f}%"
        rows.append(f"| `{intent}` | {count} | {share} |")
    table = "\n".join(rows)

    # One-line interpretation
    top_intent = next(iter(intent_counts), "unknown")
    interpretation = (
        f"**Interpretation:** {total} total queries, predominantly `{top_intent}` intent "
        f"({intent_counts.get(top_intent, 0)} queries). "
    )
    unknown_rate = intent_counts.get("unknown", 0) / total if total else 0
    if unknown_rate >= 0.20:
        interpretation += (
            f"Unknown-intent rate is elevated ({unknown_rate*100:.1f}%) — "
            "review raw logs for new intent definitions."
        )
    elif unknown_rate > 0:
        interpretation += f"Unknown-intent rate: {unknown_rate*100:.1f}%."
    else:
        interpretation += "Intent taxonomy fully covered."

    return f"{table}\n\n{interpretation}"


def _render_notes(
    kill_events: list[dict],
    trades: list[dict],
    pnl_snap: dict | None,
) -> str:
    notes = []

    # Kill switch events
    if kill_events:
        notes.append("### Kill Switch Events")
        for evt in kill_events:
            ts = evt.get("created_at", "")
            msg = evt.get("message", "")
            atype = evt.get("alert_type", "")
            notes.append(f"- **{ts}** `{atype}`: {msg}")
    else:
        notes.append("- No kill switch activations on this date.")

    # Large drawdown from snapshot
    if pnl_snap:
        equity = pnl_snap.get("portfolio_equity")
        peak = pnl_snap.get("peak_equity")
        if equity is not None and peak and peak > 0:
            dd_pct = (peak - equity) / peak * 100
            if dd_pct >= 5.0:
                notes.append(
                    f"- **DRAWDOWN ALERT:** Portfolio is {dd_pct:.2f}% below equity peak "
                    f"(${peak:,.2f} → ${equity:,.2f})."
                )

    # Large single-trade loss
    for t in trades:
        pnl = t.get("pnl") or 0.0
        if pnl <= -200:
            notes.append(
                f"- Large loss: {t.get('symbol')} {(t.get('side') or '?').upper()} "
                f"P&L ${pnl:.2f} (exit {t.get('exit_time', '')})"
            )

    return "\n".join(notes) if notes else "_No notable events._"


def render_markdown(entry: JournalEntry) -> str:
    """Combine frontmatter + body into a complete .md string."""
    fm = entry["frontmatter"]
    target_date = fm["date"]
    trades = entry.get("trades", [])
    pnl_snap = entry.get("pnl_snapshot")
    commentary = entry.get("commentary", [])
    bot_signals = entry.get("bot_signals", [])
    jarvis_asks = entry.get("jarvis_asks", {})
    kill_events = entry.get("kill_switch_events", [])
    generated_at = entry.get("generated_at", "")

    # At-a-glance stats
    trade_count = fm.get("trade_count", 0)
    daily_pnl = fm.get("daily_pnl_usd")
    win_rate = fm.get("win_rate")

    wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
    losses = sum(1 for t in trades if (t.get("pnl") or 0) < 0)

    pnl_str = f"${daily_pnl:+.2f}" if daily_pnl is not None else "N/A"
    wr_str = f"{win_rate*100:.1f}%" if win_rate is not None else "N/A"

    # Regime call from trades (most common)
    regimes = [t.get("regime") for t in trades if t.get("regime")]
    if regimes:
        regime_call = max(set(regimes), key=regimes.count)
    else:
        regime_call = "—"

    frontmatter_block = _render_frontmatter(fm)

    body = f"""# Trading Journal — {target_date}

_Generated: {generated_at}_

---

## At a Glance

| Metric | Value |
|--------|-------|
| Daily P&L | {pnl_str} |
| Trades closed | {trade_count} |
| Wins / Losses | {wins} / {losses} |
| Win rate | {wr_str} |
| Regime call | {regime_call} |

---

## Trades

{_render_trades_table(trades)}

---

## P&L Snapshot

{_render_pnl_summary(pnl_snap)}

---

## Corey Commentary Highlights

{_render_commentary(commentary)}

---

## Bot Signal Summary

{_render_bot_signals(bot_signals)}

---

## JARVIS Queries

{_render_jarvis_asks(jarvis_asks)}

---

## Notes

{_render_notes(kill_events, trades, pnl_snap)}
"""

    return f"{frontmatter_block}\n\n{body}"


# ---------------------------------------------------------------------------
# write_to_vault
# ---------------------------------------------------------------------------


def write_to_vault(entry: JournalEntry, vault_root: str) -> Path:
    """
    Write the rendered journal entry to the vault.

    Output path: <vault_root>/_session-journal/<YYYY-MM-DD>.md
    Creates parent directories as needed. Overwrites existing file (idempotent).

    Returns:
        Path of the written file.
    """
    target_date = entry["frontmatter"]["date"]
    out_dir = Path(vault_root) / "_session-journal"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{target_date}.md"
    content = render_markdown(entry)
    out_path.write_text(content, encoding="utf-8")
    logger.info("Journal written: %s", out_path)
    return out_path
