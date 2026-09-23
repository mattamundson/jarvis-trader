"""Integrity tests for the walk-forward evaluator.

The load-bearing property is NO LOOKAHEAD: the prediction for session t must not change
when later data is added or altered. Everything else is secondary, because a walk-forward
that leaks the future is worse than no evaluation at all -- it manufactures edge.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


br = _load("market_brief_base_rates", ROOT / "scripts" / "market_brief_base_rates.py")
wf = _load("market_brief_walkforward", ROOT / "scripts" / "market_brief_walkforward.py")


def synth(n: int, seed: int = 7) -> list:
    """Deterministic pseudo-random bars long enough for warmup + min_train."""
    x = seed
    bars, price = [], 4000.0
    for i in range(n):
        x = (1103515245 * x + 12345) % (2 ** 31)
        step = ((x % 2000) - 1000) / 1000.0 * 12.0
        o = price
        c = max(1.0, price + step)
        bars.append(br.Bar(f"2020-01-{i+1:03d}", round(o, 2), round(max(o, c) + 3, 2),
                           round(min(o, c) - 3, 2), round(c, 2)))
        price = c
    return bars


class NoLookaheadTests(unittest.TestCase):
    def test_predictions_do_not_change_when_future_data_is_added(self):
        """Truncating history must not alter any prediction made before the cut."""
        bars = synth(140)
        full = wf.walk_forward(bars, {}, min_train=5, warmup=10)
        cut = wf.walk_forward(bars[:120] + [], {}, min_train=5, warmup=10)
        # keep only predictions that both runs could have made: t+1 within the truncated set
        cut_dates = {r["date"] for r in cut}
        shared = [r for r in full if r["date"] in cut_dates]
        self.assertGreater(len(shared), 50, "expected a substantial overlap to compare")
        by_cut = {r["date"]: r for r in cut}
        for r in shared:
            o = by_cut[r["date"]]
            self.assertEqual(r["p_model"], o["p_model"], f"p_model leaked future at {r['date']}")
            self.assertEqual(r["p_base"], o["p_base"], f"p_base leaked future at {r['date']}")
            self.assertEqual(r["realized"], o["realized"], f"realized changed at {r['date']}")

    def test_mutating_the_future_does_not_change_past_predictions(self):
        """Corrupt every bar after the cut: predictions before it must be untouched."""
        bars = synth(140)
        clean = {r["date"]: r for r in wf.walk_forward(bars, {}, min_train=5, warmup=10)}
        tampered = list(bars)
        for i in range(100, len(tampered)):
            b = tampered[i]
            tampered[i] = br.Bar(b.date, b.open * 1.5, b.high * 1.5, b.low * 0.5, b.close * 1.4)
        after = wf.walk_forward(tampered, {}, min_train=5, warmup=10)
        for r in after:
            if r["date"] in clean and r["date"] <= bars[97].date:
                self.assertEqual(r["p_model"], clean[r["date"]]["p_model"],
                                 f"future tampering changed the prediction at {r['date']}")

    def test_train_window_never_includes_the_predicted_session(self):
        bars = synth(120)
        rows = wf.walk_forward(bars, {}, min_train=5, warmup=10)
        for r in rows:
            idx = next(i for i, b in enumerate(bars) if b.date == r["date"])
            self.assertLessEqual(r["n_train"], idx,
                                 "training window reached the session being predicted")
            self.assertLessEqual(r["n_matched"], idx)

    def test_conditional_arm_requires_min_train(self):
        bars = synth(120)
        rows = wf.walk_forward(bars, {}, min_train=10_000, warmup=10)
        self.assertTrue(rows)
        self.assertTrue(all(r["arm"] == "unconditional_fallback" for r in rows))
        # with the fallback used, model == base by construction
        for r in rows:
            self.assertEqual(r["p_model"], r["p_base"])


class ScoringTests(unittest.TestCase):
    def test_uniform_brier_is_two_thirds(self):
        for realized in wf.CLASSES:
            self.assertAlmostEqual(wf._brier(wf.UNIFORM, realized), 2.0 / 3.0, places=12)

    def test_perfect_prediction_scores_zero(self):
        p = {k: (1.0 if k == "rotation" else 0.0) for k in wf.CLASSES}
        self.assertAlmostEqual(wf._brier(p, "rotation"), 0.0, places=12)
        self.assertAlmostEqual(wf._brier(p, "failure"), 2.0, places=12)

    def test_class_rates_sum_to_100_tenths(self):
        c, r, f = br._class_rates({"continuation": 30, "rotation": 18, "failure": 10}, 58)
        self.assertEqual(round(c + r + f, 10), 100.0)

    def test_arm_summary_paired_difference_sign(self):
        # model strictly better than base on every session -> positive diff, CI above 0
        rows = []
        for i in range(30):
            rows.append({"brier_model": 0.2, "brier_base": 0.5, "brier_uniform": 0.667,
                         "top_pick": "continuation", "realized": "continuation"})
        s = wf._arm_summary(rows)
        self.assertAlmostEqual(s["paired_mean_diff_base_minus_model"], 0.3, places=9)
        self.assertTrue(s["model_beats_base"])
        self.assertEqual(s["top_pick_hit_rate"], 100.0)

    def test_arm_summary_identical_arms_do_not_beat(self):
        rows = [{"brier_model": 0.4, "brier_base": 0.4, "brier_uniform": 0.667,
                 "top_pick": "rotation", "realized": "failure"} for _ in range(30)]
        s = wf._arm_summary(rows)
        self.assertFalse(s["model_beats_base"])
        self.assertEqual(s["paired_ci95"], [0.0, 0.0])


if __name__ == "__main__":
    unittest.main()