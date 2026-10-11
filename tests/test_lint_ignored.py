"""The `denylist` check in `make lint` skips the files git ignores (template#83).

The denylist protects what is committed and published. Before the fix it read every file below the
repo root, ignored ones included: tool output in an ignored build directory or in an experiment's
`out/` log made `make lint`, and so `make guard`, fail on a tree whose pushable files were clean.

The fixture repo holds only a `harness.yaml` written here, a `.gitignore` and a README, so the
harness reports failures about files it lacks. Each test looks for one denylist line, which keeps it
independent of that baseline and of checks a later platform adds.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# scripts/lint.py imports the harness, which only a venv holding the platform packages provides.
pytest.importorskip("spicexplorer_harness.lint")

REPO = Path(__file__).resolve().parents[1]
# A made-up word, denied only in the fixture's harness.yaml. A real denylisted word written here
# would fail this repo's own denylist check: only harness.yaml and lint.py are exempt from it.
TOKEN = "ignored_wip_token"
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
# The two ignored places the issue names: a generated build directory and an experiment's log.
GITIGNORE = "doc/schematics/build/\nexperiments/*/out/\n"
IGNORED = ("doc/schematics/build/setup.txt", "experiments/001-x/out/run.log")


def _load_lint():
    import importlib.util

    spec = importlib.util.spec_from_file_location("lint_ignored_mod", REPO / "scripts" / "lint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _fixture(root: Path) -> Path:
    root.mkdir()
    (root / "harness.yaml").write_text(FIXTURE_YAML)
    (root / ".gitignore").write_text(GITIGNORE)
    (root / "README.md").write_text("# fixture\n")
    return root


@pytest.fixture
def repo(tmp_path):
    """A committed git repo with the fixture harness.yaml and the two ignore lines."""
    root = _fixture(tmp_path / "design-repo")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "fixture")
    return root


@pytest.fixture
def mod(monkeypatch):
    """scripts/lint.py without `scratch_budget`, which reads this machine's scratch work dir."""
    m = _load_lint()
    monkeypatch.setattr(m, "EXTRA", tuple(c for c in m.EXTRA if c is not m.scratch_budget))
    return m


def _write(root: Path, rel: str) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"a log line that says {TOKEN}\n")
    return f"{rel}:1: '{TOKEN}'"


def _lint(mod, root: Path, capsys) -> tuple[int, str]:
    rc = mod.main(root)
    return rc, capsys.readouterr().out


def test_a_denied_word_in_an_ignored_file_stays_green(mod, repo, capsys):
    """Only the denylist report is read: the new experiment directory fails other checks."""
    hits = [_write(repo, rel) for rel in IGNORED]
    _rc, out = _lint(mod, repo, capsys)
    assert "[denylist]" not in out
    assert not any(h in out for h in hits)


def test_a_denied_word_in_a_tracked_file_still_fails(mod, repo, capsys):
    """Committed, including a file force-added under an ignored directory: git tracks it."""
    hits = [_write(repo, "doc/notes.md"), _write(repo, "experiments/001-x/out/kept.log")]
    _git(repo, "add", "-f", "doc/notes.md", "experiments/001-x/out/kept.log")
    _git(repo, "commit", "-qm", "tracked")
    rc, out = _lint(mod, repo, capsys)
    assert rc == 1
    assert "[denylist]" in out
    assert all(h in out for h in hits)


def test_a_denied_word_in_an_untracked_file_git_does_not_ignore_still_fails(mod, repo, capsys):
    hit = _write(repo, "doc/draft.md")
    rc, out = _lint(mod, repo, capsys)
    assert rc == 1
    assert hit in out


def test_outside_a_git_checkout_every_file_is_read(mod, tmp_path, capsys):
    """No git repository, so nothing is known to be ignored: the walk reads every file, as before."""
    root = _fixture(tmp_path / "copied-by-hand")
    hits = [_write(root, rel) for rel in IGNORED]
    rc, out = _lint(mod, root, capsys)
    assert rc == 1
    assert all(h in out for h in hits)


def test_a_file_name_that_is_not_utf8_does_not_stop_the_check(mod, repo, capsys):
    """git prints names as raw bytes. A strict UTF-8 decode raised `UnicodeDecodeError`, which the
    harness reported as `[denylist] the check itself raised ...`, and no file was scanned
    (PR #84 r1). The odd-named file holds no denied word: printing such a name in a hit is the
    harness's own concern, as it was before the git filter."""
    try:
        (repo / os.fsdecode(b"bad\xff.txt")).write_text("nothing to report\n")
    except (OSError, UnicodeEncodeError):
        pytest.skip("this filesystem refuses a name that is not valid UTF-8")
    hit = _write(repo, "doc/draft.md")
    rc, out = _lint(mod, repo, capsys)
    assert rc == 1
    assert "the check itself raised" not in out
    assert hit in out


def test_a_design_inside_a_checkout_that_ignores_it_reads_every_file(mod, tmp_path, capsys):
    """No `.git` of its own, inside a checkout whose `.gitignore` lists it: that checkout's rules
    say nothing about the design, so every file is read (PR #84 r1)."""
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / ".gitignore").write_text("designs/\n")
    _git(parent, "init", "-q")
    (parent / "designs").mkdir()
    root = _fixture(parent / "designs" / "copied")
    hits = [_write(root, rel) for rel in IGNORED]
    rc, out = _lint(mod, root, capsys)
    assert rc == 1
    assert all(h in out for h in hits)
