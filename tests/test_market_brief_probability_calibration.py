import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "market_brief_probability_calibration.py"
spec = importlib.util.spec_from_file_location("market_brief_probability_calibration", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class MarketBriefProbabilityCalibrationTests(unittest.TestCase):
    def test_normalize_probs_sums_to_100(self):
        probs = module.normalize_probs(0.7, 0.2, 0.1)
        self.assertAlmostEqual(sum(probs), 100.0, places=3)
        self.assertGreater(probs[0], probs[1])
        self.assertGreater(probs[1], probs[2])

    def test_risk_off_score_prefers_continuation(self):
        regime, continuation, rotation, failure = module.score_daily_state(
            spy_gap_pct=-0.8,
            qqq_gap_pct=-1.1,
            vix_change_pct=9.0,
            es_gap_pct=-0.4,
            nq_gap_pct=-0.7,
        )
        self.assertEqual(regime, "risk_off")
        self.assertGreater(continuation, rotation)
        self.assertGreater(continuation, failure)

    def test_balanced_state_prefers_rotation(self):
        regime, continuation, rotation, failure = module.score_daily_state(
            spy_gap_pct=0.05,
            qqq_gap_pct=-0.03,
            vix_change_pct=0.2,
            es_gap_pct=0.01,
            nq_gap_pct=-0.02,
        )
        self.assertEqual(regime, "balanced")
        self.assertGreater(rotation, continuation)
        self.assertGreater(rotation, failure)

    def test_label_outcome_risk_off_continuation_failure_rotation(self):
        self.assertEqual(module.label_outcome("risk_off", -0.7, -0.5, -0.4, -0.8), "continuation")
        self.assertEqual(module.label_outcome("risk_off", 0.7, 0.6, 0.4, 0.8), "failure")
        self.assertEqual(module.label_outcome("risk_off", -0.1, 0.1, -0.05, 0.05), "rotation")

    def test_brier_score_keys(self):
        row = module.CalibrationRow(
            date="2026-01-02",
            regime="risk_off",
            continuation_probability=70.0,
            rotation_probability=20.0,
            failure_probability=10.0,
            label="continuation",
            spy_gap_pct=-1.0,
            qqq_gap_pct=-1.0,
            vix_change_pct=8.0,
            es_gap_pct=-0.5,
            nq_gap_pct=-0.5,
            spy_open_to_close_pct=-0.5,
            qqq_open_to_close_pct=-0.5,
            es_open_to_close_pct=-0.5,
            nq_open_to_close_pct=-0.5,
            source_quality="daily_proxy",
        )
        scores = module.brier_score([row])
        self.assertEqual(set(scores), {"continuation", "rotation", "failure", "macro_avg"})
        self.assertAlmostEqual(scores["continuation"], 0.09, places=6)
        self.assertAlmostEqual(scores["rotation"], 0.04, places=6)
        self.assertAlmostEqual(scores["failure"], 0.01, places=6)


if __name__ == "__main__":
    unittest.main()
