#!/usr/bin/env python3
"""Provider-monitor cron script: polls /health, detects provider changes, alerts Discord."""
from __future__ import annotations
import json, os, sys, urllib.request, logging
from pathlib import Path
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("provider-monitor")

ENGINE = Path(__file__).resolve().parent.parent
STATE = ENGINE / "data" / "provider_state.json"
URL = "http://127.0.0.1:8010/health"
DISCORD = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()

def ts(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def load():
    if STATE.exists():
        try: return json.loads(STATE.read_text("utf-8"))
        except: pass
    return {"p": None, "a": None, "boot": False}

def save(s):
    t = STATE.with_suffix(".tmp")
    t.write_text(json.dumps(s, indent=2), "utf-8")
    t.replace(STATE)

def health():
    try:
        r = urllib.request.urlopen(urllib.request.Request(URL), timeout=10)
        return json.loads(r.read()) if r.status == 200 else None
    except: return None

def discord(msg):
    if not DISCORD: return False
    try:
        r = urllib.request.urlopen(urllib.request.Request(DISCORD, data=json.dumps({"content": msg, "username": "JARVIS"}).encode(), headers={"Content-Type": "application/json"}, method="POST"), timeout=10)
        ok = r.status in (200, 204)
        if ok: log.info("discord ok")
        return ok
    except Exception as e: log.warning("discord fail: %s", e); return False

def run():
    h = health()
    if not h: log.error("unreachable"); return 1
    lp = h.get("llm_providers", {})
    if not lp: log.info("no llm_providers yet"); return 0
    p, a, cf = lp.get("primary_provider"), lp.get("active_provider"), lp.get("providers_configured", [])
    s = load()
    alerts = []
    # primary config change
    if p and s.get("p") and p != s["p"]:
        alerts.append("[JARVIS ALERT] LLM primary provider changed | Before: {} -> Now: {} | Active: {} | Configured: {}".format(s["p"], p, a or "(none)", ", ".join(cf)))
    # failover
    if a and p and a != p and s.get("boot") and a != s.get("a"):
        alerts.append("[JARVIS ALERT] LLM Provider failover | Primary: {} -> Active: {} | Configured: {}".format(p, a, ", ".join(cf)))
    # recovery
    if a and p and a == p and s.get("boot") and s.get("a") and s["a"] != a:
        alerts.append("[JARVIS ALERT] LLM Provider restored to primary | Provider: {} | Configured: {}".format(a, ", ".join(cf)))
    save({"p": p, "a": a, "boot": True})
    for msg in alerts:
        log.warning(msg)
        discord(msg)
    if not alerts:
        st = "ok" if a == p else "FAILOVER({})".format(a)
        log.info("p=%s a=%s [%s]", p, a, st)
    return 0

if __name__ == "__main__":
    sys.exit(run())