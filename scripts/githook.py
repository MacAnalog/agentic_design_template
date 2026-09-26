#!/usr/bin/env python3
"""`make hook-install` / `make hook-remove`: the OPT-IN pre-push guard hook.

`make guard` is the gate (tree clean, lint green, tests green). This script is the half that
makes it un-forgettable for the people who want that: a `pre-push` hook that runs `make guard`
and refuses the push when it is red.

It is opt-in on purpose, and `make init` does NOT install it. The lab's standing stance is that
a hook which blocks ordinary work gets removed — the only hook a session runs by default is the
NDA kit-tree ask-hook, which asks rather than blocks. A guard hook is per clone, costs whatever
this design's `make test` costs, and is a choice its owner makes once per checkout.

Two behaviours worth knowing before installing:

* **`core.hooksPath` is honoured.** The hook is written to `git rev-parse --git-path hooks`, so a
  clone that redirects its hooks elsewhere gets it there, not in a `.git/hooks` nothing reads.
* **Linked worktrees SHARE that directory** (it lives in the common git dir), so installing from
  one worktree guards every worktree of the repo — including a fresh one where `make init` has
  not run yet and `make lint` is therefore red. That is precisely why the refusal names
  `git push --no-verify`.

Nothing here clobbers a hook somebody else wrote: an existing `pre-push` without this script's
marker line is left alone and reported.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = "pre-push"
# How `remove` and the `make lint` INFO line recognise OUR hook and nobody else's.
MARKER = "# agentic-design-template: pre-push guard (make hook-install / make hook-remove)"

SCRIPT = f"""#!/bin/sh
{MARKER}
# Installed by `make hook-install`, removed by `make hook-remove`. Edits are lost on re-install.
# Git runs this from the top of the working tree; be explicit anyway (a hook invoked by other
# tooling has been seen with a different cwd).
cd "$(git rev-parse --show-toplevel)" || exit 1
# A push from a linked worktree runs this hook with GIT_DIR set to that worktree's git dir. Left
# set, it sends the `git init` / `git commit` calls `make test` makes in tmp dirs into this repo.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

make guard && exit 0

cat >&2 <<'SXGUARD'

REFUSING: `make guard` is red, so nothing was pushed.
  Fix what it named above, or bypass it DELIBERATELY and visibly:
    GUARD_SKIP_TEST=1 git push ...   # keep the tree + lint clauses, drop the test clause
    git push --no-verify ...         # skip this hook entirely
  (`make hook-remove` uninstalls the hook for good.)
SXGUARD
exit 1
"""


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"git {' '.join(args)} failed in {repo}: {r.stderr.strip()}")
    return r.stdout.strip()


def hooks_dir(repo: Path = REPO) -> Path:
    """The directory git actually reads hooks from — `core.hooksPath` included.

    `git rev-parse --git-path hooks` answers that question for us (it returns the configured
    path when one is set, `.git/hooks` otherwise) and its answer is relative to the repo root,
    so it is resolved against `repo` rather than the caller's cwd.
    """
    return (repo / _git(repo, "rev-parse", "--git-path", "hooks")).resolve()


def hook_path(repo: Path = REPO) -> Path:
    return hooks_dir(repo) / HOOK


def state(repo: Path = REPO) -> str:
    """`ours` (this script's hook), `foreign` (somebody else's), or `absent`."""
    p = hook_path(repo)
    if not p.exists():
        return "absent"
    return "ours" if MARKER in p.read_text(errors="replace") else "foreign"


def install(repo: Path = REPO) -> int:
    p, how = hook_path(repo), state(repo)
    if how == "foreign":
        print(f"REFUSING: {p} already exists and this script did not write it.")
        print("  Nothing was changed. Merge `make guard` into that hook yourself, or move it "
              "aside and re-run `make hook-install`.")
        return 2
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(SCRIPT)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    verb = "re-installed" if how == "ours" else "installed"
    print(f"pre-push guard {verb}: {p}")
    print("  it runs `make guard` before every push; `git push --no-verify` bypasses it "
          "deliberately, `GUARD_SKIP_TEST=1 git push` drops only the test clause.")
    if p.parent != (repo / ".git" / "hooks").resolve():
        print("  (core.hooksPath points here; linked worktrees of this repo share it)")
    return 0


def remove(repo: Path = REPO) -> int:
    p, how = hook_path(repo), state(repo)
    if how == "absent":
        print(f"no pre-push guard hook to remove ({p})")
        return 0
    if how == "foreign":
        print(f"REFUSING: {p} was not written by `make hook-install` — left untouched.")
        return 2
    p.unlink()
    print(f"pre-push guard removed: {p}")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "install":
        return install()
    if cmd == "remove":
        return remove()
    print(__doc__.splitlines()[0])
    print("usage: scripts/githook.py install|remove   (via `make hook-install` / `make hook-remove`)")
    return 2


if __name__ == "__main__":
    os.chdir(REPO)
    sys.exit(main(sys.argv))
