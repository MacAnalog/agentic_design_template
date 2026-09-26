"""pytest scratch lives under $SX_SCRATCH (never /tmp): the lane rejects /tmp work roots.

No test or fixture sees GIT_DIR, GIT_WORK_TREE or GIT_INDEX_FILE from the caller's environment.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# A push from a linked worktree runs the pre-push hook with GIT_DIR set. A hook installed by an
# older scripts/githook.py does not unset it and passes it on to `make test`. While one of these
# is set, the `git init` / `git add` / `git commit` calls the tests make in tmp dirs write into the
# repo it names: commits on the pushed branch, core.bare=true in its config.
_GIT_REPO_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")


@pytest.fixture(scope="session", autouse=True)
def _no_inherited_git_repo():
    """Remove `_GIT_REPO_VARS` for the whole session.

    Session scope, so the variables are gone before any module- or function-scoped fixture runs git.
    """
    with pytest.MonkeyPatch.context() as mp:
        for name in _GIT_REPO_VARS:
            mp.delenv(name, raising=False)
        yield


def pytest_configure(config):
    if not config.option.basetemp:
        root = Path(os.environ.get("SX_SCRATCH") or Path.home() / "sx-scratch")
        base = root / "pytest" / Path(__file__).resolve().parents[1].name
        base.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(base)
