"""Bonus: Inspect AI port of 3 graders must agree cell-by-cell with the pydantic-evals graders.
Skipped when inspect-ai is not installed (it is optional, not in requirements-lab9.txt)."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.student


def test_inspect_scorers_agree_with_pydantic_evals_on_seeded_regression():
    pytest.importorskip("inspect_ai")
    from lab9 import inspect_port

    ok, total, agg, diffs = inspect_port.compare("seeded_regression", Path("config/metric_spec.yaml"))
    assert diffs == [] and ok == total == 14 * 5 * 3
    assert agg["refund_amount_correct"] == (0.8571, 0.8571)
    assert agg["reply_matches_ledger"] == (0.7857, 0.7857)
