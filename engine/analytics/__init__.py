"""Analytics package.

Lazy exports (PEP 562): submodules that pull in pandas/numpy native DLLs are
imported on first attribute access, NOT at package import. Stdlib-only
consumers (outcome_hygiene, the digest generator) must stay importable even
when native DLLs are blocked -- the 2026-06-10 Smart App Control incident
killed the calibration alarm precisely because this package eagerly imported
gate_v2_calibrator (pandas) on ``import analytics``.
"""

from importlib import import_module

_LAZY_EXPORTS = {
    "CURRENT_THRESHOLDS": ".gate_v2_calibrator",
    "collect_historical_verdicts": ".gate_v2_calibrator",
    "diff_vs_current": ".gate_v2_calibrator",
    "recommended_thresholds": ".gate_v2_calibrator",
    "render_vault_markdown": ".gate_v2_calibrator",
    "MTFConfirmationFilter": ".mtf_confirmation",
    "MTFConfirmationResult": ".mtf_confirmation",
    "TimeframeSignal": ".mtf_confirmation",
    "VIXOverlay": ".vix_overlay",
    "VIXState": ".vix_overlay",
    "classify_vix": ".vix_overlay",
}

_LAZY_SUBMODULES = {"gate_v2_calibrator", "mtf_confirmation", "vix_overlay"}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    if name in _LAZY_SUBMODULES:
        module = import_module("." + name, __name__)
        globals()[name] = module
        return module
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(target, __name__), name)
    globals()[name] = value  # cache so __getattr__ runs once per name
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__) | _LAZY_SUBMODULES)
