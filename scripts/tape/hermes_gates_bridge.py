"""Hermes -> /tape gates bridge (stdlib only, read-only on Hermes files).

Hermes does not write a gates.md. What it does write is the pre-market readiness report
(second-brain/reports/premarket/PREMARKET_<date>.md) and the approved safety record next to it.
Those files also contain dollar and P&L text, so the page must never read them directly.
This bridge reads them and writes <tape state>/gates.md containing ONLY allow-listed gate names
and a pass/warn/fail word, which `readHermesGates` (dashboard/lib/hermesGates.ts) already parses.

Honesty rules:
  * the readiness report is a once-a-day artifact: if it is not from today the readiness gate and
    its failing checks are shown as WARN with the age in the name, never as a fresh result;
  * the lockout line is only written when today's report states the kill switch;
  * the approved safety record is a human sign-off, labelled as such, not live state;
  * a check name that is not on the allow-list is dropped, never echoed.

  python hermes_gates_bridge.py            write gates.md once
  python hermes_gates_bridge.py --selftest
"""
from __future__ import annotations
import argparse, json, os, re, sys
from datetime import date, datetime
from pathlib import Path

PREMARKET_DIR = Path(os.environ.get("HERMES_PREMARKET_DIR") or (Path.home() / "master-jarvis" / "second-brain" / "reports" / "premarket"))
# readiness check name (lower case, as printed by jarvis_premarket_readiness.py) -> public label
CHECKS = {
    "engine reachable": "Engine reachable",
    "safety: paper mode": "Safety: paper mode",
    "safety: live trading off": "Safety: live trading OFF",
    "safety state matches approved record": "Safety state matches approved record",
    "ib gateway alive": "IB gateway alive",
    "ib data leg connected": "IB data leg connected",
    "ib execution verified": "IB execution verified",
    "database connected": "Database connected",
    "vix percentile available": "VIX percentile available",
    "dashboard serving": "Dashboard serving",
    "ledger trusted": "Ledger trusted",
    "not halted": "Not halted",
    "ib_account_id matches gateway": "Broker id matches gateway",
}
HEADER = re.compile(r"READINESS\s+[—-]\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+[—-]\s+(PASS|FAIL)\s+\((\d+)/(\d+)\s+checks\)", re.I)
FAIL_LINE = re.compile(r"^\s*FAIL\s+(.+?)(?::\s.*)?$")
KILL = re.compile(r"kill_switch=(True|False)")


def latest_report(d: Path) -> Path | None:
    try:
        files = sorted(d.glob("PREMARKET_????-??-??.md"))
    except OSError:
        return None
    return files[-1] if files else None


def canon(raw: str) -> str | None:
    n = raw.strip().lower()
    if n in CHECKS:
        return CHECKS[n]
    if re.match(r"^[a-z0-9_]+ bar is from today$", n):
        return "Bar is from today"
    if re.match(r"^[a-z0-9_]+ source agreement$", n):
        return "Source agreement"
    return None


def build(report_text: str | None, record: dict | None, today: date) -> str:
    out = ["# Hermes gates (sanitised bridge; names and status only)"]
    fresh = False
    if report_text:
        m = HEADER.search(report_text)
        if m:
            rdate = date.fromisoformat(m.group(1))
            age = (today - rdate).days
            fresh = age == 0
            passed = m.group(3).upper() == "PASS"
            tag = f"{m.group(4)} of {m.group(5)}"
            when = "today" if fresh else f"{rdate.isoformat()}, {age}d old"
            status = ("pass" if passed else "fail") if fresh else "warn"
            out.append(f"- Premarket readiness {tag} ({when}): {status}")
            seen = set()
            for line in report_text.splitlines():
                f = FAIL_LINE.match(line)
                if not f:
                    continue
                label = canon(f.group(1))
                if label and label not in seen:
                    seen.add(label)
                    out.append(f"- {label}{'' if fresh else ' (last report)'}: {'fail' if fresh else 'warn'}")
            k = KILL.search(report_text)
            if fresh and k:
                out.append(f"lockout: {'on' if k.group(1) == 'True' else 'off'}")
        else:
            out.append("- Premarket readiness report unreadable: warn")
    else:
        out.append("- Premarket readiness report not found: warn")
    if isinstance(record, dict):
        when = str(record.get("approved_at", ""))[:10]
        tag = f" (approved {when})" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", when) else ""
        if "paper_mode" in record:
            out.append(f"- Paper mode, approved record{tag}: {'pass' if record['paper_mode'] is True else 'fail'}")
        if "live_trading" in record:
            out.append(f"- Live trading OFF, approved record{tag}: {'pass' if record['live_trading'] is False else 'fail'}")
        if "kill_switch_active" in record:
            out.append(f"- Kill switch clear, approved record{tag}: {'pass' if record['kill_switch_active'] is False else 'fail'}")
    return "\n".join(out) + "\n"


def run(pdir: Path | None = None, out_dir: Path | None = None, today: date | None = None) -> str:
    pdir = pdir or PREMARKET_DIR
    out_dir = out_dir or Path(os.environ.get("TAPE_STATE_DIR") or (Path.home() / "tape" / "state"))
    rep = latest_report(pdir)
    text = None
    if rep:
        try:
            text = rep.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = None
    rec = None
    try:
        rec = json.loads((pdir / "approved_safety_state.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    md = build(text, rec, today or date.today())
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "gates.md.tmp"
    tmp.write_text(md, encoding="utf-8")
    os.replace(tmp, out_dir / "gates.md")
    return md


def selftest() -> int:
    rep = ("JARVIS PRE-MARKET READINESS — 2026-10-20 09:18 — FAIL (12/15 checks)\n"
           "  FAIL  ib gateway alive: False\n  FAIL  IB_ACCOUNT_ID matches gateway: configured_present=True gateway_account_count=1\n"
           "  FAIL  some secret thing: $5,000 pnl\nGUARDRAILS: positions=0 daily_pnl=0.0 halted=False target=500.0 | kill_switch=False paper=True live=False\n")
    rec = dict(kill_switch_active=False, paper_mode=True, live_trading=False, approved_at="2026-09-18", note="$ pnl")
    old = build(rep, rec, date(2026, 10, 26))
    assert "Premarket readiness 12 of 15 (2026-10-20, 6d old): warn" in old, old
    assert "IB gateway alive (last report): warn" in old and "Broker id matches gateway (last report): warn" in old
    assert "lockout" not in old and "secret" not in old and "$" not in old and "pnl" not in old.lower() and "account" not in old.lower()
    new = build(rep, rec, date(2026, 10, 20))
    assert "(today): fail" in new and "- IB gateway alive: fail" in new and "lockout: off" in new
    assert "Paper mode, approved record (approved 2026-09-18): pass" in new
    assert "not found" in build(None, None, date(2026, 10, 20))
    print("selftest ok")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    print(run())
