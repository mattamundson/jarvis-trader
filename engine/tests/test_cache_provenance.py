"""Tests for `_gate_v2_helpers.cache_provenance`.

Context (2026-09-17 audit, `docs/research/verdict-artifact-audit-2026-09-17.md`): ZERO of 76
verdict artifacts recorded which cache they ran on, so no "validated on deep data" claim was
independently verifiable. Filename labels proved unreliable — 8 duplicate-content groups (19
files) filed the same bytes under `-deep-`, `-pre-deep-`, and `-shallow-contaminated-` names.

The deep-cache test is a **provenance lock**: if the certified deep cache is present and its
content hash no longer matches the recorded constant, that is a deliberate signal to re-verify
the cache (and update the constant) rather than a test to silence.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

os.environ.setdefault("API_KEY", "local-research-sandbox-dummy-not-a-credential")

import pytest

from backtest._gate_v2_helpers import cache_provenance

#: Recorded in the JARVIS rules for MES_2019-05-05_2026-08-26_1h.csv (43,010 bars, 7.31y).
DEEP_CACHE_NAME = "MES_2019-05-05_2026-08-26_1h.csv"
DEEP_CACHE_SHA256 = "e26631c012b128284e61526dad78e7d39a3c180634dad7398a7dd8cc225f83fe"
DEEP_CACHE_ROWS = 43010
CACHE_DIR = Path(__file__).resolve().parents[1] / "backtest" / "cache"


def _write(tmp_path: Path, text: str, name: str = "X_2020-01-01_2024-01-01_1h.csv") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_rows_span_and_hash_are_computed_from_content(tmp_path):
    body = (
        "timestamp,open,high,low,close\n"
        "2021-01-04 09:00:00+00:00,100,101,99,100.5\n"
        "2021-01-04 10:00:00+00:00,100.5,102,100,101.5\n"
        "2021-01-04 11:00:00+00:00,101.5,103,101,102.5\n"
    )
    p = _write(tmp_path, body)
    prov = cache_provenance(p)

    assert prov["cache_rows"] == 3
    assert prov["cache_span_first"].startswith("2021-01-04 09:00:00")
    assert prov["cache_span_last"].startswith("2021-01-04 11:00:00")
    assert prov["cache_bytes"] == len(p.read_bytes())
    assert prov["cache_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert prov["cache_file"] == p.name


def test_hash_changes_when_content_changes(tmp_path):
    a = _write(tmp_path, "timestamp,open,high,low,close\n2021-01-04 09:00:00+00:00,1,1,1,1\n", "a.csv")
    b = _write(tmp_path, "timestamp,open,high,low,close\n2021-01-04 09:00:00+00:00,1,1,1,2\n", "b.csv")
    assert a != b
    assert cache_provenance(a)["cache_sha256"] != cache_provenance(b)["cache_sha256"]


def test_missing_file_is_reported_not_raised(tmp_path):
    prov = cache_provenance(tmp_path / "nope.csv")
    assert prov["error"] == "cache_not_found"
    assert prov["cache_file"] == "nope.csv"


def test_short_span_is_flagged_as_non_deep(tmp_path):
    """A ~2y span must be flagged: shallow data does not certify edge."""
    body = "timestamp,open,high,low,close\n" + "".join(
        f"2024-01-0{i} 09:00:00+00:00,1,1,1,1\n" for i in range(1, 6)
    ) + "2025-12-31 09:00:00+00:00,1,1,1,1\n"
    prov = cache_provenance(_write(tmp_path, body))
    assert prov["cache_span_years"] < 5.0
    assert "does not meet the deep-data standard" in prov["provenance_note"]


def test_unparseable_timestamps_are_reported_not_raised(tmp_path):
    prov = cache_provenance(_write(tmp_path, "timestamp,open\nNOT_A_DATE,1\nALSO_NOT,2\n"))
    assert prov["provenance_note"] == "span unparseable from cache timestamps"


def test_inject_cache_provenance_from_path(tmp_path):
    """The injector is what each runner calls; verify both input modes."""
    from backtest._gate_v2_helpers import inject_cache_provenance

    p = _write(tmp_path, "timestamp,open,high,low,close\n2021-01-04 09:00:00+00:00,1,1,1,1\n")
    doc = inject_cache_provenance({"symbol": "X"}, p)
    assert doc["cache_provenance"]["cache_file"] == "a.csv" or doc["cache_provenance"]["cache_file"].endswith(".csv")
    assert doc["cache_provenance"]["cache_rows"] == 1
    assert doc["symbol"] == "X"  # untouched


def test_inject_cache_provenance_prefers_df_attrs():
    import pandas as pd

    from backtest._gate_v2_helpers import inject_cache_provenance

    df = pd.DataFrame({"close": [1.0]})
    df.attrs["cache_provenance"] = {"cache_file": "from_attrs.csv", "cache_sha256": "deadbeef"}
    doc = inject_cache_provenance({}, df=df)
    assert doc["cache_provenance"]["cache_file"] == "from_attrs.csv"


def test_inject_cache_provenance_never_raises_on_bad_input():
    from backtest._gate_v2_helpers import inject_cache_provenance

    doc = inject_cache_provenance({})  # no df, no path
    assert doc["cache_provenance"]["error"] == "provenance_unavailable"
    doc2 = inject_cache_provenance({}, 12345)  # bogus path type
    assert "cache_provenance" in doc2


@pytest.mark.skipif(not (CACHE_DIR / DEEP_CACHE_NAME).exists(), reason="deep cache not present")
def test_deep_cache_provenance_lock():
    """Provenance lock on the certified MES deep cache."""
    prov = cache_provenance(CACHE_DIR / DEEP_CACHE_NAME)
    assert prov["cache_rows"] == DEEP_CACHE_ROWS
    assert prov["cache_sha256"] == DEEP_CACHE_SHA256
    assert prov["cache_span_first"].startswith("2019-05-05")
    assert prov["cache_span_last"].startswith("2026-08-26")
    assert prov["cache_span_years"] > 7.0
    # A cache that meets the deep standard must NOT carry a non-deep note.
    assert "provenance_note" not in prov
