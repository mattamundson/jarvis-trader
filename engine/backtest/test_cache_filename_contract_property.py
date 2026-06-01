"""
Property-based tests for the cache filename contract — P3-38.

Uses Hypothesis to generate thousands of random filenames and verify that
the CACHE_FILENAME_CONTRACT regex correctly partitions them into valid/invalid.

Also uses Hypothesis to stress-test _find_latest_cache() selection logic:
- Among any set of conforming files, the one with the lexicographically
  greatest end-date segment is always selected (ISO YYYY-MM-DD sorts correctly).
- Off-contract files are never preferred over a conforming sibling.

Run:  cd engine && .venv/Scripts/python backtest/test_cache_filename_contract_property.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from backtest._gate_v2_helpers import _find_latest_cache
from backtest.export_ibkr_history import CACHE_FILENAME_CONTRACT

# ---------------------------------------------------------------------------
# Generators for the contract fields
# ---------------------------------------------------------------------------

SYMBOLS = st.from_regex(r"[A-Z][A-Z0-9]{1,3}", fullmatch=True)
ISO_DATES = st.dates(
    min_value=__import__("datetime").date(2010, 1, 1),
    max_value=__import__("datetime").date(2030, 12, 31),
).map(lambda d: d.strftime("%Y-%m-%d"))
INTERVALS = st.sampled_from(["1h", "2h", "4h", "8h", "12h", "1d", "4d", "12d", "99d"])

# Valid contract filename strategy
_valid_filename = st.builds(
    lambda sym, s, e, iv: f"{sym}_{s}_{e}_{iv}.csv",
    sym=SYMBOLS,
    s=ISO_DATES,
    e=ISO_DATES,
    iv=INTERVALS,
)


# ---------------------------------------------------------------------------
# P: valid-struct filenames always accepted by regex
# ---------------------------------------------------------------------------


@given(_valid_filename)
@settings(max_examples=2000, deadline=None)
def test_contract_accepts_all_valid_struct(filename: str) -> None:
    """Every filename generated from the contract grammar must match the regex."""
    assert CACHE_FILENAME_CONTRACT.match(
        filename
    ), f"Contract regex rejected a structurally valid filename: {filename!r}"


# ---------------------------------------------------------------------------
# P: mutated filenames with known violations are rejected
# ---------------------------------------------------------------------------


_COMMON_VIOLATIONS = [
    # lowercase symbol
    st.builds(
        lambda sym, s, e, iv: f"{sym.lower()}_{s}_{e}_{iv}.csv",
        sym=SYMBOLS,
        s=ISO_DATES,
        e=ISO_DATES,
        iv=INTERVALS,
    ),
    # uppercase interval suffix
    st.builds(
        lambda sym, s, e, iv: f"{sym}_{s}_{e}_{iv.upper()}.csv",
        sym=SYMBOLS,
        s=ISO_DATES,
        e=ISO_DATES,
        iv=INTERVALS,
    ),
    # missing .csv extension
    st.builds(
        lambda sym, s, e, iv: f"{sym}_{s}_{e}_{iv}",
        sym=SYMBOLS,
        s=ISO_DATES,
        e=ISO_DATES,
        iv=INTERVALS,
    ),
    # leading underscore
    st.builds(
        lambda sym, s, e, iv: f"_{sym}_{s}_{e}_{iv}.csv",
        sym=SYMBOLS,
        s=ISO_DATES,
        e=ISO_DATES,
        iv=INTERVALS,
    ),
    # 5-char symbol (too long)
    st.builds(
        lambda sym, s, e, iv: f"{sym}X_{s}_{e}_{iv}.csv",
        sym=st.from_regex(r"[A-Z][A-Z0-9]{3}", fullmatch=True),
        s=ISO_DATES,
        e=ISO_DATES,
        iv=INTERVALS,
    ),
    # 1-char symbol (too short)
    st.builds(
        lambda sym, s, e, iv: f"{sym}_{s}_{e}_{iv}.csv",
        sym=st.from_regex(r"[A-Z]", fullmatch=True),
        s=ISO_DATES,
        e=ISO_DATES,
        iv=INTERVALS,
    ),
    # missing end-date segment
    st.builds(lambda sym, s, iv: f"{sym}_{s}_{iv}.csv", sym=SYMBOLS, s=ISO_DATES, iv=INTERVALS),
]


@given(st.one_of(*_COMMON_VIOLATIONS))
@settings(max_examples=500, deadline=None)
def test_contract_rejects_known_violations(filename: str) -> None:
    """Known-invalid filenames must never match the contract regex."""
    assert not CACHE_FILENAME_CONTRACT.match(
        filename
    ), f"Contract regex accepted a known-invalid filename: {filename!r}"


# ---------------------------------------------------------------------------
# P: _find_latest_cache always picks the greatest end-date among conforming
# ---------------------------------------------------------------------------


def _make_file(d: Path, name: str) -> None:
    (d / name).write_text("ts,open,high,low,close,volume\n")


@given(
    st.lists(
        st.builds(
            lambda sym, s, e, iv: (sym, s, e, iv),
            sym=SYMBOLS,
            s=ISO_DATES,
            e=ISO_DATES,
            iv=st.just("1h"),
        ),
        min_size=2,
        max_size=10,
    )
)
@settings(max_examples=300, deadline=None)
def test_find_latest_cache_always_picks_max_end_date(rows: list) -> None:
    """_find_latest_cache returns the file with the lexicographically max end-date."""
    # Fix symbol so all files are candidates for the same lookup
    sym = rows[0][0]
    names = [f"{sym}_{s}_{e}_1h.csv" for _, s, e, _ in rows]

    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        for name in names:
            _make_file(d, name)

        result = _find_latest_cache(d, sym, "_1h.csv")

        # The selected file must have the max end-date segment.
        # When multiple files share the same end-date, any of them is acceptable.
        best_end = max(n.split("_")[2] for n in names)
        result_end = result.name.split("_")[2]
        assert result_end == best_end, (
            f"Selected file has end-date {result_end!r}, "
            f"best available is {best_end!r}. "
            f"Got {result.name!r} from names: {names}"
        )


@given(
    st.lists(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd", "P", "S"),
                blacklist_characters='/\\:*?"<>|',
            ),
            min_size=1,
            max_size=20,
        ),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=200, deadline=None)
def test_off_contract_never_beats_conforming_sibling(junk_names: list) -> None:
    """Off-contract filenames mixed with one conforming file: conforming always wins."""
    conforming = "MES_2024-01-01_2026-05-07_1h.csv"
    with tempfile.TemporaryDirectory() as tmpdir:
        d = Path(tmpdir)
        _make_file(d, conforming)
        for junk in junk_names:
            # Ensure junk ends in _1h.csv so it's a candidate but off-contract
            candidate = junk.replace("_", "") + "_1h.csv"
            assume(CACHE_FILENAME_CONTRACT.match(candidate) is None)
            try:
                _make_file(d, candidate)
            except OSError:
                pass  # Some generated names are not valid filenames — skip

        result = _find_latest_cache(d, "MES", "_1h.csv")
        assert (
            result.name == conforming
        ), f"Off-contract file beat conforming sibling. Got {result.name!r}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> None:
    tests = [
        test_contract_accepts_all_valid_struct,
        test_contract_rejects_known_violations,
        test_find_latest_cache_always_picks_max_end_date,
        test_off_contract_never_beats_conforming_sibling,
    ]
    failures = []
    for t in tests:
        print(f"Running {t.__name__} ...", end=" ", flush=True)
        try:
            t()
            print("PASS")
        except Exception as exc:
            print(f"FAIL\n  {exc}")
            failures.append(t.__name__)

    print(f"\n{'=' * 60}")
    if failures:
        print(f"FAILED {len(failures)}/{len(tests)}: {', '.join(failures)}")
        sys.exit(1)
    else:
        print(f"ALL {len(tests)} property-based tests PASSED.")
        sys.exit(0)


if __name__ == "__main__":
    main()
