"""Guard for conftest's opt-in-only handling of order-placing broker tests."""

from __future__ import annotations

import os

import pytest
from conftest import _IB_ORDER_TESTS_OPT_IN_ENV, _marker_positively_selected


@pytest.mark.parametrize(
    ("markexpr", "expected"),
    [
        ("", False),
        ("not slow", False),
        ("not slow and not manual", False),
        ("not manual and not integration_ib", False),
        ("integration_ib", True),
        ("slow and integration_ib", True),
        ("not slow and integration_ib", True),
    ],
)
def test_integration_ib_selection(markexpr, expected):
    assert _marker_positively_selected(markexpr, "integration_ib") is expected


@pytest.mark.integration_ib
def test_integration_ib_marked_test_is_skipped_without_opt_in(request):
    """Must never execute under a plain fast-suite run such as -m "not slow"."""


    markexpr = request.config.getoption("markexpr", default="") or ""
    opted_in = _marker_positively_selected(markexpr, "integration_ib") or (
        os.environ.get(_IB_ORDER_TESTS_OPT_IN_ENV) == "1"
    )
    assert opted_in, "integration_ib test executed without explicit opt-in"
