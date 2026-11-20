import pandas as pd
from backtest import score_row, oos_score_eval
from pathlib import Path

import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[3])

DATA = (TAPE_ROOT / "system/regime/data/sessions_labeled.csv")


def test_score_row_monday_negative():
    s = score_row({"dow": 0, "is_event": 0, "vix_prior": 18, "ovn_atr": 0.6})
    # monday -2, vix 15-20 +1, mod ovn +1 → 0
    assert s == 0


def test_score_row_event_wed():
    s = score_row({"dow": 2, "is_event": 1, "vix_prior": 18, "ovn_atr": 0.6})
    # event +2, wed +1, vix +1, mod ovn +1 → 5
    assert s == 5


def test_oos_buckets_monotonic_high_vs_low():
    if not DATA.exists():
        return
    df = pd.read_csv(DATA)
    res = oos_score_eval(df, stage2=False)
    low = next(b for b in res["buckets"] if b["bucket"] == "low")
    high = next(b for b in res["buckets"] if b["bucket"] == "high")
    assert high["n"] >= 20
    assert high["trend_rate"] >= low["trend_rate"] - 0.02  # allow tiny noise
