from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFRESH = ROOT / "scripts" / "refresh_phase0_runtime_snapshot.ps1"
INSTALL = ROOT / "scripts" / "install_phase0_runtime_snapshot_task.ps1"


def test_refresh_wrapper_invokes_read_only_snapshot_producer_without_secret_args():
    text = REFRESH.read_text(encoding="utf-8")
    assert "phase0_runtime_truth_snapshot.py" in text
    assert "--force" in text
    assert "--engine-url" in text
    assert "--output" in text
    assert "ConvertFrom-Json" in text
    assert "secrets_included" in text
    assert "API_KEY" not in text
    assert "JARVIS_API_KEY" not in text
    assert "IB_ACCOUNT" not in text


def test_scheduled_task_installer_runs_wrapper_every_five_minutes_by_default():
    text = INSTALL.read_text(encoding="utf-8")
    assert "Jarvis-A01-RuntimeSnapshotRefresh" in text
    assert "[int]$EveryMinutes = 5" in text
    assert "schtasks.exe" in text
    assert "/SC MINUTE" in text
    assert "/MO $EveryMinutes" in text
    assert "/Run" in text
    assert "refresh_phase0_runtime_snapshot.ps1" in text
    assert "API_KEY" not in text
    assert "JARVIS_API_KEY" not in text
    assert "IB_ACCOUNT" not in text
