import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


br = load("market_brief_base_rates")
sc = load("market_brief_scorecard")


class BaseRatesTests(unittest.TestCase):
    def test_classify_state_buckets(self):
        self.assertEqual(br.classify_state(False, 14.0, 3.0), "not_ath_close")
        self.assertEqual(br.classify_state(True, 14.0, 3.0), "ath_close_lowvol_accel_gt2")
        self.assertEqual(br.classify_state(True, 14.0, 1.0), "ath_close_lowvol_accel_0to2")
        self.assertEqual(br.classify_state(True, 22.0, 3.0), "ath_close_hivol")
        self.assertEqual(br.classify_state(True, None, 3.0), "ath_close_hivol")
        self.assertEqual(br.classify_state(True, 14.0, None), "ath_close_lowvol_unknown")

    def test_label_partition_is_a_strict_partition(self):
        # up close -> continuation regardless of the low
        self.assertEqual(br.label_partition(101, 90, 100, 95), "continuation")
        # down close, breaks low -> failure
        self.assertEqual(br.label_partition(99, 94, 100, 95), "failure")
        # down close, holds low -> rotation
        self.assertEqual(br.label_partition(99, 95, 100, 95), "rotation")

    def test_summarize_partitions_sum_to_100(self):
        bars = [br.Bar(f"2026-01-{i+1:02d}", 100, 101, 99, 100) for i in range(40)]
        recs = br.build_records(bars, {b.date: 14.0 for b in bars})
        st = br.summarize(recs, bars, "not_ath_close")
        if st.n:
            self.assertAlmostEqual(st.p_continuation + st.p_rotation + st.p_failure, 100.0, places=1)


class ScorecardTests(unittest.TestCase):
    def test_validate_brief_requires_sum_100(self):
        ok = {"date": "2026-09-21", "symbol": "ES=F", "continuation": 56.0, "rotation": 26.0, "failure": 18.0}
        self.assertEqual(sc.validate_brief(ok), [])
        bad = dict(ok, continuation=90.0)
        self.assertTrue(any("sum to 100" in e for e in sc.validate_brief(bad)))

    def test_append_and_read_ledger_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            led = pathlib.Path(td) / "ledger.jsonl"
            rec = {"date": "2026-09-21", "symbol": "ES=F", "continuation": 56.0,
                   "rotation": 26.0, "failure": 18.0, "signal_close": 7828.0,
                   "signal_low": 7742.5, "state": "ath_close_lowvol_accel_gt2"}
            sc.append_brief(rec, led)
            entries = sc.read_ledger(led)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["date"], "2026-09-21")
            self.assertEqual(entries[0]["safety"]["mode"], "ANALYSIS_ONLY")
            self.assertFalse(entries[0]["safety"]["orders_enabled"])

    def test_append_brief_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            led = pathlib.Path(td) / "ledger.jsonl"
            with self.assertRaises(ValueError):
                sc.append_brief({"date": "2026-09-21", "symbol": "ES=F",
                                 "continuation": 10.0, "rotation": 10.0, "failure": 10.0}, led)

    def test_label_partition_matches_base_rates_module(self):
        self.assertEqual(sc.label_partition(101, 90, 100, 95), br.label_partition(101, 90, 100, 95))
        self.assertEqual(sc.label_partition(99, 94, 100, 95), br.label_partition(99, 94, 100, 95))
        self.assertEqual(sc.label_partition(99, 95, 100, 95), br.label_partition(99, 95, 100, 95))


if __name__ == "__main__":
    unittest.main()