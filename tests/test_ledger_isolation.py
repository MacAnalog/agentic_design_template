"""`tests/conftest.py`: no test appends to this checkout's own ledger (template#60).

`certify()` logs its `evidence: awaiting` row from `spicexplorer_harness.certify`, a module the
`_certify_env` fixture never patched, so every `make test` left placeholder `evaluate` rows in
`runs/ledger.ndjson` that `make runs --fails` and the context pack then reported as design runs.
"""

from __future__ import annotations

from pathlib import Path

from spicexplorer_harness import load, log_run

REPO = Path(__file__).resolve().parents[1]


def test_a_row_logged_against_this_checkout_lands_in_the_test_ledger():
    h = load(REPO)
    real = REPO / h.ledger
    before = real.read_bytes() if real.exists() else None
    log_run(h, "ledger-isolation-probe", {"x": 1.0})
    after = real.read_bytes() if real.exists() else None
    assert after == before, f"a test appended to {real}"
    assert "ledger-isolation-probe" in h.path(h.ledger).read_text()


def test_a_harness_on_another_root_keeps_its_own_ledger(tmp_path):
    (tmp_path / "harness.yaml").write_text((REPO / "harness.yaml").read_text())
    h = load(tmp_path)
    assert h.path(h.ledger) == tmp_path / h.ledger
