"""`make skills-update` before `make init`.

Until `make init` has run, `.sx/skills` is the empty directory a clone leaves for a submodule it
has not initialised. It has no `.git`, so `git -C .sx/skills ...` finds the repository above it,
the design's own: the recipe's fetch and checkout moved the design's HEAD from its branch to a
detached `origin/main`, and the recipe then failed on the missing `sx-link`. The recipe now
refuses unless `.sx/skills/.git` exists.

Both tests run this repo's real `skills-update` recipe in a temporary git repository that holds
the tracked files the recipe reads (`Makefile`, `.gitmodules`, the `.claude/` links), with every
`GIT_*` variable of the caller removed and no user or system git config.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and k not in ("MAKEFLAGS", "MAKELEVEL", "MFLAGS")}
    return {**env, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def _run(cwd: Path, *cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, env=_env())


def git(cwd: Path, *args: str) -> str:
    r = _run(cwd, "git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
             *args)
    assert r.returncode == 0, f"git {' '.join(args)}\n{r.stdout}{r.stderr}"
    return r.stdout.strip()


def head(root: Path) -> tuple[str, str]:
    return git(root, "rev-parse", "--abbrev-ref", "HEAD"), git(root, "rev-parse", "HEAD")


def design(tmp_path: Path) -> Path:
    """A design repository on branch `probe`, one commit ahead of the `main` its `origin` holds,
    so a checkout of `origin/main` would move HEAD. `.sx/skills` is an empty directory."""
    ls = subprocess.run(["git", "ls-files", "-z", "--", "Makefile", ".gitmodules", ".claude"],
                        cwd=REPO, capture_output=True, text=True, check=False)
    if ls.returncode:
        pytest.skip("not a git checkout: there are no tracked files to copy")
    root = tmp_path / "design"
    for rel in filter(None, ls.stdout.split("\0")):
        src, dst = REPO / rel, root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            dst.symlink_to(os.readlink(src))
        elif src.is_file():
            shutil.copy2(src, dst)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "main")
    git(tmp_path, "init", "-q", "--bare", "origin.git")
    git(root, "remote", "add", "origin", str(tmp_path / "origin.git"))
    git(root, "push", "-q", "origin", "main")
    git(root, "switch", "-q", "-c", "probe")
    git(root, "commit", "-q", "--allow-empty", "-m", "probe")
    (root / ".sx" / "skills").mkdir(parents=True, exist_ok=True)
    return root


def test_skills_update_refuses_before_init_and_leaves_the_design_head(tmp_path):
    root = design(tmp_path)
    before = head(root)
    r = _run(root, "make", "skills-update")
    out = r.stdout + r.stderr
    assert head(root) == before, out
    assert r.returncode == 2, out
    assert "REFUSING: .sx/skills is not initialised" in out and "run 'make init' first" in out, out


def test_skills_update_accepts_a_submodule_whose_git_is_a_file(tmp_path):
    """After `make init`, `.sx/skills/.git` is a file that points into the design's
    `.git/modules/`. The recipe runs, moves `.sx/skills` to its `origin/main` and leaves the
    design's HEAD where it was."""
    root = design(tmp_path)
    lib = tmp_path / "library"
    (lib / "bin").mkdir(parents=True)
    (lib / "bin" / "sx-link").write_text("#!/bin/sh\nexit 0\n")
    (lib / "bin" / "sx-link").chmod(0o755)
    git(lib, "init", "-q", "-b", "main")
    git(lib, "add", "-A")
    git(lib, "commit", "-qm", "pinned")
    skills = root / ".sx" / "skills"
    skills.rmdir()
    git(tmp_path, "clone", "-q", f"--separate-git-dir={tmp_path / 'skills.git'}", str(lib),
        str(skills))
    assert (skills / ".git").is_file()
    git(lib, "commit", "-q", "--allow-empty", "-m", "the library's main moves")
    before = head(root)
    r = _run(root, "make", "skills-update")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert head(root) == before, out
    assert git(skills, "rev-parse", "HEAD") == git(lib, "rev-parse", "HEAD"), out
