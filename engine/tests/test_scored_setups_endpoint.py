"""Tests for the read-only GET /trades/scored-setups endpoint (proof record)."""

from __future__ import annotations

import json

from routers import trades_router as T

RECORD = {
    "generated_ct": "2026-10-29 10:53 CT",
    "r_basis": "1R = entry to actual stop",
    "goal_setups": 20,
    "counted": 99,  # stale header value: aggregates must be recomputed from rows
    "avg_R": 9.9,
    "setups": [
        {
            "date": "2026-09-23",
            "setup": "8am fade",
            "side": "short",
            "entry": "7818.75",
            "stop": "7837",
            "exit": "7781",
            "entry_time": "",
            "R": 2.08,
            "rule_breaks": 0,
            "counted": True,
        },
        {
            "date": "2026-10-28",
            "setup": "8am bounce",
            "side": "long",
            "entry": "7755",
            "stop": "",
            "R": -1.0,
            "rule_breaks": 1,
            "counted": True,
        },
        {"date": "2026-10-29", "setup": "8am fade", "side": "short", "R": None, "counted": False},
    ],
}


def test_scored_setups_reads_proof_record(tmp_path, monkeypatch) -> None:
    p = tmp_path / "proof-record.json"
    p.write_text(json.dumps(RECORD), encoding="utf-8")
    monkeypatch.setenv("JARVIS_PROOF_RECORD_PATH", str(p))

    resp = T.get_scored_setups()
    assert resp.available is True
    assert resp.source == "proof-record.json"
    assert resp.goal_setups == 20
    assert resp.counted == 2
    assert resp.wins == 1 and resp.losses == 1
    assert resp.avg_r == 0.54
    assert resp.total_r == 1.08
    assert len(resp.setups) == 3
    first = resp.setups[0]
    assert first.entry == 7818.75 and first.stop == 7837.0 and first.entry_time is None
    assert resp.setups[1].stop is None
    assert resp.setups[2].counted is False


def test_scored_setups_missing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_PROOF_RECORD_PATH", str(tmp_path / "nope.json"))
    resp = T.get_scored_setups()
    assert resp.available is False
    assert resp.counted == 0
    assert resp.error == "proof record not found"


def test_scored_setups_malformed_file(tmp_path, monkeypatch) -> None:
    p = tmp_path / "proof-record.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("JARVIS_PROOF_RECORD_PATH", str(p))
    resp = T.get_scored_setups()
    assert resp.available is False
    assert resp.error == "proof record unreadable"


def test_scored_setups_route_is_get_only() -> None:
    methods = {
        m
        for r in T.router.routes
        if getattr(r, "path", "") == "/trades/scored-setups"
        for m in r.methods
    }
    assert methods == {"GET"}
