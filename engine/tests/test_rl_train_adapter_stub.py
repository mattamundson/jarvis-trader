"""
Regression — RL train adapter must not masquerade a stub as real training.

The non-baseline path previously called compute_baseline_val_bpb() identical to
--baseline and emitted stub mfu=0.0 / peak_vram_gb=0.0, silently contaminating
any RL hyperparameter sweep with fake "trained" metrics. It must now fail loudly
until RLTrainer().train_walkforward() is actually wired.
"""

from __future__ import annotations

import pytest

from autoresearch import rl_train_adapter as adapter


def test_baseline_path_prints_val_bpb(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["rl_train_adapter", "--baseline"])
    rc = adapter.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "val_bpb=" in out
    # Baseline value is the negated best-known MES composite.
    assert "val_bpb=-0.8537" in out


def test_non_baseline_path_raises_not_implemented(monkeypatch):
    # No --baseline → the real training path, which is not wired, must raise
    # rather than silently returning the baseline value.
    monkeypatch.setattr("sys.argv", ["rl_train_adapter"])
    with pytest.raises(NotImplementedError, match="not wired"):
        adapter.main()


def test_compute_baseline_is_deterministic():
    assert adapter.compute_baseline_val_bpb() == pytest.approx(-0.8537)
