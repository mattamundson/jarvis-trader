"""I7: analytics package must not eagerly import pandas.

The 2026-06-10 Smart App Control incident blocked native DLLs; everything
that merely imported ``analytics`` (e.g. the stdlib-only calibration alarm
via outcome_hygiene) died on the eager gate_v2_calibrator -> pandas chain.
These tests pin the lazy-import contract with fresh-interpreter subprocesses.
"""

import subprocess
import sys
from pathlib import Path

ENGINE_ROOT = str(Path(__file__).resolve().parent.parent)


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=ENGINE_ROOT,
        timeout=120,
    )


def test_import_analytics_does_not_import_pandas():
    proc = _run(
        "import sys; import analytics; "
        "assert 'pandas' not in sys.modules, 'pandas was imported eagerly'; "
        "print('OK')"
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_outcome_hygiene_importable_when_pandas_is_broken():
    # Simulate the SAC scenario: any pandas import raises ImportError.
    code = (
        "import sys\n"
        "class _Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'pandas' or name.startswith('pandas.'):\n"
        "            raise ImportError('pandas blocked (simulated SAC)')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Block())\n"
        "import analytics\n"
        "from analytics import outcome_hygiene\n"
        "print('OK')\n"
    )
    proc = _run(code)
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_lazy_exports_still_resolve():
    proc = _run(
        "from analytics import VIXOverlay, classify_vix, CURRENT_THRESHOLDS; "
        "import analytics; "
        "assert analytics.MTFConfirmationFilter is not None; "
        "assert analytics.vix_overlay.VIXOverlay is VIXOverlay; "
        "print('OK')"
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_unknown_attribute_raises():
    proc = _run(
        "import analytics\n"
        "try:\n"
        "    analytics.not_a_real_symbol\n"
        "except AttributeError:\n"
        "    print('OK')\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout
