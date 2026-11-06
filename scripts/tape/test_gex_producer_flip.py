"""Flip null / out-of-range regressions for scripts/tape/gex_producer.py.

Run from repo root:
  python scripts/tape/gex_producer.py --selftest
  python scripts/tape/test_gex_producer_flip.py
  python -m pytest scripts/tape/test_gex_producer_flip.py -q   # if pytest installed
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_PATH = Path(__file__).with_name("gex_producer.py")
_spec = importlib.util.spec_from_file_location("gex_producer", _PATH)
assert _spec and _spec.loader
gp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gp)


class TestGexProducerFlip(unittest.TestCase):
    def test_numeric_flip_ok(self):
        g = gp.parse(gp.SAMPLE)
        self.assertIsNotNone(g)
        assert g is not None
        self.assertEqual(g["flip"], 7776)
        self.assertEqual(g["flip_status"], "ok")

    def test_null_flip_unresolved_keeps_walls(self):
        g = gp.parse(gp.SAMPLE_NULL_FLIP)
        self.assertIsNotNone(g)
        assert g is not None
        self.assertIsNone(g["flip"])
        self.assertEqual(g["flip_status"], "unresolved")
        self.assertEqual(g["put_wall"], 7027.75)
        self.assertEqual(g["call_wall"], 7730.5)

    def test_spy_scale_flip_rejected(self):
        g = gp.parse(gp.SAMPLE_SPY_SCALE)
        self.assertIsNotNone(g)
        assert g is not None
        self.assertIsNone(g["flip"])
        self.assertEqual(g["flip_status"], "unresolved")

    def test_build_emits_cta_fields(self):
        g = gp.parse(gp.SAMPLE_NULL_FLIP)
        self.assertIsNotNone(g)
        assert g is not None
        out = gp.build(None, g, gp.datetime(2026, 11, 5, 17, 10, tzinfo=gp.CT))
        self.assertEqual(out["symbol"], "ES")
        self.assertIsNone(out["flip"])
        self.assertEqual(out["flip_status"], "unresolved")
        self.assertIn("source_ts", out)
        self.assertIn("received_ts", out)
        self.assertEqual(out["put_wall"], 7027.75)

    def test_builtin_selftest(self):
        self.assertEqual(gp.selftest(), 0)


if __name__ == "__main__":
    unittest.main()
