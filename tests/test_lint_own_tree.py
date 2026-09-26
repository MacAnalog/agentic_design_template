"""The tree walks in `make lint` skip a nested checkout's files (template#40).

A nested checkout is a directory inside this repo that holds its own `.git`: a git worktree under
`.claude/worktrees/<name>/` (its `.git` is a one-line file naming this repo's git directory), or a
clone. A parallel session keeps its uncommitted work there, and its own `make lint` checks it.

Before the fix, the parent's lint read those files too: one denylisted word in a paused session's
notes made `make lint` fail in a parent checkout whose own files were clean.

The fixture repo holds only a `harness.yaml` written here, a `.gitignore` and a README, so the
harness reports failures about files it lacks. Each test compares the report before and
after planting files, which keeps it independent of that baseline and of checks a later platform
adds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# scripts/lint.py imports the harness, which only a venv holding the platform packages provides.
harness_lint = pytest.importorskip("spicexplorer_harness.lint")

REPO = Path(__file__).resolve().parents[1]
# A made-up word, denied only in the fixture's harness.yaml. A real denylisted word written here
# would fail this repo's own denylist check: only harness.yaml and lint.py are exempt from it.
TOKEN = "nested_wip_token"
FIXTURE_YAML = """\
name: fixture
package: design
exp_env: EXP
jobs_env: JOBS
spec:
  - {key: gain_db, label: gain, op: ">=", bound: 60, unit: dB}
denylist:
  - {pattern: "\\\\bTOKEN\\\\b", why: test fixture}
""".replace("TOKEN", TOKEN)
# A scorecard with a provenance block whose script hash matches no file: `scorecard-recompute`
# fails it wherever its search for `scorecard.json` finds it.
STALE_CARD = {"scorecard": {"gain_db": 62.4},
              "provenance": {"script": "design/metrics.py", "script_sha": "0" * 64}}


def _load_lint():
    import importlib.util

    spec = importlib.util.spec_from_file_location("lint_own_tree_mod", REPO / "scripts" / "lint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                    *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A committed git repo with the fixture harness.yaml and this template's worktree ignore."""
    root = tmp_path / "design-repo"
    root.mkdir()
    (root / "harness.yaml").write_text(FIXTURE_YAML)
    (root / ".gitignore").write_text(".claude/worktrees/\n")
    (root / "README.md").write_text("# fixture\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "fixture")
    return root


@pytest.fixture
def mod(monkeypatch):
    """scripts/lint.py without `scratch_budget`. That check reads this machine's scratch work dir,
    not the repo, and a simulation writing there between two runs would change the report."""
    m = _load_lint()
    monkeypatch.setattr(m, "EXTRA", tuple(c for c in m.EXTRA if c is not m.scratch_budget))
    return m


def _worktree(root: Path, name: str = "paused-session") -> Path:
    """A real git worktree at `.claude/worktrees/<name>/`, where this template's sessions keep theirs."""
    wt = root / ".claude" / "worktrees" / name
    _git(root, "worktree", "add", "-q", "-b", f"feat/{name}", str(wt))
    assert (wt / ".git").is_file()
    return wt


def _plant(d: Path) -> None:
    """Uncommitted work in `d`: a note with the denied word, a scorecard with a stale hash, and a
    figure outside every directory the `artifact-home` check accepts (it lists files with
    `git ls-files`, so an uncommitted one is never reported, nested or not; it is added to show
    that this does not change)."""
    (d / "doc").mkdir(parents=True, exist_ok=True)
    (d / "doc" / "wip-notes.md").write_text(f"a draft that still says {TOKEN}\n")
    card = d / "experiments" / "007-wip" / "scorecard.json"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(json.dumps(STALE_CARD))
    (d / "report").mkdir(exist_ok=True)
    (d / "report" / "eye.png").write_bytes(b"")


def _lint(mod, root: Path, capsys) -> tuple[int, str]:
    rc = mod.main(root)
    return rc, capsys.readouterr().out


def test_a_nested_worktree_changes_nothing_in_the_parent_report(mod, repo, capsys):
    """The denied word and the stale scorecard both are files in a paused session's worktree."""
    before = _lint(mod, repo, capsys)
    _plant(_worktree(repo))
    after = _lint(mod, repo, capsys)
    assert after == before
    assert ".claude/worktrees" not in after[1]


def test_a_nested_worktree_is_skipped_on_a_harness_that_walks_into_it(mod, repo, capsys,
                                                                      monkeypatch):
    """Before platform #269 the harness had no nested-checkout skip and walked every directory.
    `SX_ROOT` decides which platform a design runs, so the template cannot assume the newer one."""
    monkeypatch.setattr(harness_lint, "_is_nested_checkout", lambda d: False, raising=False)
    before = _lint(mod, repo, capsys)
    _plant(_worktree(repo))
    after = _lint(mod, repo, capsys)
    assert after == before
    assert ".claude/worktrees" not in after[1]


def test_a_plain_subdirectory_with_the_same_files_still_fails(mod, repo, capsys):
    """The skip depends on a `.git` entry, not on the directory's name or place: without one, the
    directory is part of this checkout, and both checks report it."""
    _rc, before = _lint(mod, repo, capsys)
    _plant(repo / ".claude" / "worktrees" / "not-a-checkout")
    rc, after = _lint(mod, repo, capsys)
    assert rc == 1
    denied = f".claude/worktrees/not-a-checkout/doc/wip-notes.md:1: '{TOKEN}'"
    stale = "[scorecard-recompute] .claude/worktrees/not-a-checkout/experiments/007-wip/"
    assert denied in after and denied not in before
    assert stale in after and stale not in before


def test_the_worktree_still_fails_its_own_lint(mod, repo, capsys):
    """The files are not hidden from every lint: the checkout they belong to still reports them."""
    wt = _worktree(repo)
    _plant(wt)
    rc, out = _lint(mod, wt, capsys)
    assert rc == 1
    assert f"doc/wip-notes.md:1: '{TOKEN}'" in out
    assert "[scorecard-recompute] experiments/007-wip/scorecard.json" in out


def test_a_design_check_skips_the_worktree_only_when_it_walks_with_own_tree_walk(
        mod, repo, capsys, monkeypatch):
    """A check a design adds to EXTRA runs inside `main`, as the scripts/lint.py docstring says.

    `own_tree_walk` skips the worktree. `os` in scripts/lint.py is not replaced, so `os.walk`
    there still enters it: the docstring tells a check author to use `own_tree_walk`.
    """
    seen: dict[str, set[str]] = {"own_tree_walk": set(), "os.walk": set()}

    def design_check(L) -> None:
        for label, walk in (("own_tree_walk", mod.own_tree_walk), ("os.walk", mod.os.walk)):
            for root, _dirs, names in walk(L.h.root):
                seen[label].update((Path(root) / n).relative_to(L.h.root).as_posix()
                                   for n in names)

    monkeypatch.setattr(mod, "EXTRA", (*mod.EXTRA, design_check))
    _plant(_worktree(repo))
    _lint(mod, repo, capsys)
    planted = ".claude/worktrees/paused-session/doc/wip-notes.md"
    assert "README.md" in seen["own_tree_walk"]
    assert not any(p.startswith(".claude/worktrees/") for p in seen["own_tree_walk"])
    assert planted in seen["os.walk"]


def test_a_git_file_or_directory_marks_a_nested_checkout(tmp_path, mod):
    """A worktree's `.git` is a file and a clone's is a directory; both are skipped."""
    (tmp_path / "clone" / ".git").mkdir(parents=True)
    (tmp_path / "worktree").mkdir()
    (tmp_path / "worktree" / ".git").write_text("gitdir: elsewhere\n")
    (tmp_path / "plain").mkdir()
    assert mod.is_nested_checkout(tmp_path / "clone")
    assert mod.is_nested_checkout(tmp_path / "worktree")
    assert not mod.is_nested_checkout(tmp_path / "plain")


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 directory")
def test_an_unreadable_directory_is_not_treated_as_a_checkout(tmp_path, mod):
    """`stat` on its `.git` raises PermissionError; the answer is "no", not a crashed lint."""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        assert not mod.is_nested_checkout(locked)
    finally:
        locked.chmod(0o755)


def test_own_tree_walk_stops_at_a_nested_checkout_but_not_at_the_top(tmp_path, mod):
    """The repo root holds a `.git` too; only the directories below it are tested."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "doc").mkdir()
    (tmp_path / "doc" / "a.md").write_text("x")
    wt = tmp_path / ".claude" / "worktrees" / "w"
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: elsewhere\n")
    (wt / "b.md").write_text("x")

    def files(walk):
        return {(Path(r) / f).relative_to(tmp_path).as_posix()
                for r, _dirs, names in walk(tmp_path) for f in names}

    assert files(os.walk) == {"doc/a.md", ".claude/worktrees/w/.git", ".claude/worktrees/w/b.md"}
    assert files(mod.own_tree_walk) == {"doc/a.md"}


def test_own_tree_only_replaces_os_walk_for_the_run_and_restores_it(mod):
    fake = type(sys)("fake_harness_lint")
    fake.os = os
    with mod.own_tree_only(fake):
        assert fake.os.walk is mod.own_tree_walk
        assert fake.os.path is os.path and fake.os.sep == os.sep   # every other name is `os`'s
    assert fake.os is os
    with pytest.raises(RuntimeError), mod.own_tree_only(fake):
        raise RuntimeError("a check crashed")
    assert fake.os is os                                           # restored after an error too


def test_own_tree_only_leaves_a_module_without_os_alone(mod):
    """A harness that no longer imports `os` walks some other way: nothing to replace, no crash."""
    fake = type(sys)("fake_harness_lint")
    with mod.own_tree_only(fake):
        assert not hasattr(fake, "os")
    assert not hasattr(fake, "os")
