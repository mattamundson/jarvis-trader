#!/usr/bin/env python3
"""
Deterministic structural-level engine for the market-framing-brief skill.

The brief's levels must be DERIVED, not parroted. This computes a Corey-style
level ladder from OHLC alone — classic floor-trader pivots plus prior-session
and overnight rails — so the brief always has a reproducible level set even when
the engine IB feed and the HiddenPivots endpoint are unreachable.

Inputs are the PRIOR completed session's high/low/close (the pivot basis), plus
optional overnight Globex high/low (the pre-open rails). No third-party
"published levels", no cash+basis guess, no dependencies.

Usage:
  python compute_levels.py --sym NQ --ph 29744 --pl 29493.5 --pc 29727.75 \
                           --onh 29744 --onl 29493.5 --open 29535.75
"""
from __future__ import annotations

import argparse


def floor_pivots(h: float, l: float, c: float) -> dict[str, float]:
    """Classic floor-trader pivots from prior-session H/L/C."""
    rng = h - l
    p = (h + l + c) / 3
    return {
        "R3": h + 2 * (p - l),
        "R2": p + rng,
        "R1": 2 * p - l,
        "P": p,
        "S1": 2 * p - h,
        "S2": p - rng,
        "S3": l - 2 * (h - p),
    }


def build(sym, ph, pl, pc, onh=None, onl=None, day_open=None) -> str:
    piv = floor_pivots(ph, pl, pc)
    mid = (ph + pl) / 2  # prior-session midpoint ≈ value reference
    out = [f"== {sym} level ladder (deterministic, from prior session OHLC) =="]
    out.append(f"  prior session: H {ph:.2f}  L {pl:.2f}  C {pc:.2f}  (range {ph - pl:.2f})")
    if onh is not None and onl is not None:
        out.append(f"  overnight rails: ONH {onh:.2f}  ONL {onl:.2f}")
    out.append("  --- resistance ---")
    for k in ("R3", "R2", "R1"):
        out.append(f"  {k:>3}: {piv[k]:.2f}")
    out.append(f"  PIVOT(P): {piv['P']:.2f}   prior-mid/value: {mid:.2f}")
    out.append("  --- support ---")
    for k in ("S1", "S2", "S3"):
        out.append(f"  {k:>3}: {piv[k]:.2f}")
    # Bias hint relative to the pivot, using overnight close proxy or last open.
    ref = day_open if day_open is not None else pc
    lean = "above pivot — constructive lean" if ref > piv["P"] else "below pivot — cautious lean"
    out.append(f"  reference ({ref:.2f}) is {lean}")
    out.append("  NOTE: deterministic geometry only. Catalyst/regime decide direction;")
    out.append("        prefer engine /levels (HiddenPivots) when reachable.")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", required=True)
    ap.add_argument("--ph", type=float, required=True, help="prior-session high")
    ap.add_argument("--pl", type=float, required=True, help="prior-session low")
    ap.add_argument("--pc", type=float, required=True, help="prior-session close")
    ap.add_argument("--onh", type=float, default=None, help="overnight high")
    ap.add_argument("--onl", type=float, default=None, help="overnight low")
    ap.add_argument("--open", dest="day_open", type=float, default=None)
    a = ap.parse_args()
    print(build(a.sym, a.ph, a.pl, a.pc, a.onh, a.onl, a.day_open))


if __name__ == "__main__":
    main()
