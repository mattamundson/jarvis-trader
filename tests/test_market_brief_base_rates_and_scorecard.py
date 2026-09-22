import importlib.util
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

    def test_class_rates_sum_to_exactly_100(self):
        """Regression: independent 1dp rounding produced 99.9 totals."""
        # 30/18/10 of n=58 rounds independently to 51.7 + 31.0 + 17.2 = 99.9
        c, r, f = br._class_rates({"continuation": 30, "rotation": 18, "failure": 10}, 58)
        self.assertEqual(round(c + r + f, 10), 100.0)
        self.assertEqual((c, r, f), (51.7, 31.0, 17.3))

    def test_class_rates_sums_exactly_100_across_many_n(self):
        for n in range(1, 200):
            for a in range(n + 1):
                for b in range(n - a + 1):
                    counts = {"continuation": a, "rotation": b, "failure": n - a - b}
                    c, r, f = br._class_rates(counts, n)
                    self.assertEqual(round(c + r + f, 10), 100.0, f"n={n} counts={counts}")

    def test_class_rates_handles_zero_n(self):
        self.assertEqual(br._class_rates({"continuation": 0, "rotation": 0, "failure": 0}, 0),
                         (0.0, 0.0, 0.0))


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


class DailyPreregistrationTests(unittest.TestCase):
    def _payload(self, date="2026-09-21"):
        return {
            "today": {"date": date, "close": 7829.25, "low": 7713.75, "state": "ath_close_lowvol_accel_gt2"},
            "probabilities": {"continuation": 55.6, "rotation": 25.9, "failure": 18.5, "sum": 100.0},
            "matched_state": "ath_close_lowvol_accel_gt2",
        }

    def test_records_then_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            led = pathlib.Path(td) / "ledger.jsonl"
            status, entry = br.record_daily(self._payload(), led)
            self.assertEqual(status, "recorded")
            self.assertEqual(entry["date"], "2026-09-21")
            self.assertEqual(entry["safety"]["mode"], "ANALYSIS_ONLY")
            self.assertFalse(entry["safety"]["orders_enabled"])
            self.assertEqual(len(led.read_text(encoding="utf-8").splitlines()), 1)
            # second run on the same session must not duplicate the row
            status2, _ = br.record_daily(self._payload(), led)
            self.assertEqual(status2, "exists")
            self.assertEqual(len(led.read_text(encoding="utf-8").splitlines()), 1)

    def test_force_rewrites_a_second_row(self):
        with tempfile.TemporaryDirectory() as td:
            led = pathlib.Path(td) / "ledger.jsonl"
            br.record_daily(self._payload(), led)
            status, _ = br.record_daily(self._payload(), led, force=True)
            self.assertEqual(status, "recorded")
            self.assertEqual(len(led.read_text(encoding="utf-8").splitlines()), 2)

    def test_different_session_dates_coexist(self):
        with tempfile.TemporaryDirectory() as td:
            led = pathlib.Path(td) / "ledger.jsonl"
            br.record_daily(self._payload("2026-09-18"), led)
            status, _ = br.record_daily(self._payload("2026-09-21"), led)
            self.assertEqual(status, "recorded")
            self.assertEqual(len(led.read_text(encoding="utf-8").splitlines()), 2)

    def test_skips_when_payload_lacks_date(self):
        with tempfile.TemporaryDirectory() as td:
            led = pathlib.Path(td) / "ledger.jsonl"
            status, _info = br.record_daily({"today": {}, "probabilities": {}}, led)
            self.assertEqual(status, "skipped")
            self.assertFalse(led.exists())

    def test_tolerates_malformed_ledger_lines(self):
        with tempfile.TemporaryDirectory() as td:
            led = pathlib.Path(td) / "ledger.jsonl"
            led.write_text("{not json}\n", encoding="utf-8")
            status, _ = br.record_daily(self._payload(), led)
            self.assertEqual(status, "recorded")

    def test_recorded_row_is_scoreable_by_the_scorecard(self):
        """The pre-registered row must satisfy the scorer's contract."""
        with tempfile.TemporaryDirectory() as td:
            led = pathlib.Path(td) / "ledger.jsonl"
            br.record_daily(self._payload(), led)
            rows = sc.read_ledger(led)
            self.assertEqual(len(rows), 1)
            self.assertEqual(sc.validate_brief(rows[0]), [])


if __name__ == "__main__":
    unittest.main()