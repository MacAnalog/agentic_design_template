"""pytest scratch lives under $SX_SCRATCH (never /tmp): the lane rejects /tmp work roots.

Each checkout has its own base folder, `pytest/<folder name>-<first 8 hex of the sha256 of its
resolved path>`: pytest empties the base folder when a run starts, so two checkouts with the same
folder name must not share one (template#43).

No test or fixture sees GIT_DIR, GIT_WORK_TREE or GIT_INDEX_FILE from the caller's environment,
nor the commercial-kit variables SX_KIT_FILE and SX_KIT_SKILLS: a design on `lane: bridge` exports
both, and a test that needs one sets it itself.

No test appends to this checkout's own ledger: a row logged against it lands in the test's
`tmp_path` instead (template#60).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

# A push from a linked worktree runs the pre-push hook with GIT_DIR set. A hook installed by an
# older scripts/githook.py does not unset it and passes it on to `make test`. While one of these
# is set, the `git init` / `git add` / `git commit` calls the tests make in tmp dirs write into the
# repo it names: commits on the pushed branch, core.bare=true in its config.
_GIT_REPO_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
# A bridge-lane account exports these; inherited, they add `--library <clone>` to every
# `make skills-update` a test runs and make `make layout-flow` take the kit lane's checks.
_KIT_VARS = ("SX_KIT_FILE", "SX_KIT_SKILLS")
_CHECKOUT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _no_inherited_git_repo_or_kit():
    """Remove `_GIT_REPO_VARS` and `_KIT_VARS` for the whole session.

    Session scope, so the variables are gone before any module- or function-scoped fixture runs git.
    """
    with pytest.MonkeyPatch.context() as mp:
        for name in (*_GIT_REPO_VARS, *_KIT_VARS):
            mp.delenv(name, raising=False)
        yield


@pytest.fixture(autouse=True)
def _ledger_in_tmp(monkeypatch, tmp_path):
    """Point this checkout's ledger at `tmp_path` for every test.

    The ledger is written from several modules (`metrics.run_decks`, the lifecycle,
    `certify_dir`), each holding its own `log_run` and its own loaded `Harness`, so patching a
    writer misses the next one added. Every write resolves its file through `Harness.path`, so the
    redirect is there. A harness on another root (a test's tmp repo) keeps its own ledger.
    """
    from spicexplorer_harness.config import Harness

    real = Harness.path

    def path(self: Harness, rel: str) -> Path:
        if rel == self.ledger and Path(self.root).resolve() == _CHECKOUT:
            return tmp_path / "ledger.ndjson"
        return real(self, rel)

    monkeypatch.setattr(Harness, "path", path)


def pytest_configure(config):
    if not config.option.basetemp:
        root = Path(os.environ.get("SX_SCRATCH") or Path.home() / "sx-scratch")
        checkout = Path(__file__).resolve().parents[1]
        tag = hashlib.sha256(str(checkout).encode()).hexdigest()[:8]
        base = root / "pytest" / f"{checkout.name}-{tag}"
        base.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(base)
