"""`make guard` and the opt-in pre-push hook (`scripts/githook.py`).

The guard is a Makefile recipe, so the tests drive the REAL recipe: each one builds a throwaway
git repo, copies this repo's `Makefile` into it and appends stub `lint:` / `test:` recipes. GNU
make takes the LAST recipe for a target (it warns "overriding recipe", on stderr), so `guard`
runs verbatim while its two expensive clauses become one `echo` each. Rewriting the recipe in the
test instead would have tested the copy.

The hook half is exercised end to end against a bare remote on a path: `git push --dry-run` does
run `pre-push`, which is what makes a refusal testable without a network or a second repo host.

`MAKEFLAGS` / `MAKELEVEL` are stripped from every subprocess because pytest itself is running
under `make test`, and an inherited `MAKELEVEL` turns the inner make chatty.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GITHOOK = REPO / "scripts" / "githook.py"


def _load_githook():
    """`scripts/githook.py` as its own module (it is a script, not an installed package)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("githook_under_test", GITHOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _env() -> dict[str, str]:
    e = {k: v for k, v in os.environ.items()
         if k not in ("MAKEFLAGS", "MAKELEVEL", "MFLAGS", "GUARD_SKIP_TEST")}
    return e


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
        cwd=root, capture_output=True, text=True, env=_env())


def make(root: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(["make", *args], cwd=root, capture_output=True, text=True,
                          env={**_env(), **env})


def repo(tmp_path: Path, lint: str = "@echo lint-ok", test: str = "@echo test-ok") -> Path:
    """A git repo running this repo's real `guard` recipe over stubbed lint/test clauses."""
    root = tmp_path / "r"
    root.mkdir()
    shutil.copy(REPO / "Makefile", root / "Makefile")
    with (root / "Makefile").open("a") as f:
        f.write(f"\n\n# test stubs (last recipe wins)\nlint:\n\t{lint}\ntest:\n\t{test}\n")
    (root / "README.md").write_text("stub\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "initial")
    return root


# --------------------------------------------------------------------------- the guard clauses

def test_guard_passes_on_a_clean_green_tree(tmp_path):
    r = make(repo(tmp_path), "guard")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "tree clean, lint green, tests green" in r.stdout
    assert "REFUSING" not in r.stdout


def test_guard_refuses_an_unstaged_edit(tmp_path):
    root = repo(tmp_path)
    (root / "README.md").write_text("edited, not staged\n")
    r = make(root, "guard")
    assert r.returncode != 0
    assert "REFUSING: unstaged changes in the tree" in r.stdout


def test_guard_refuses_a_staged_but_uncommitted_edit(tmp_path):
    """The window `git diff --quiet` alone lets through — the reporter's point in #31."""
    root = repo(tmp_path)
    (root / "README.md").write_text("edited and staged\n")
    git(root, "add", "-A")
    r = make(root, "guard")
    assert r.returncode != 0
    assert "REFUSING: staged but uncommitted changes" in r.stdout
    assert "unstaged changes" not in r.stdout        # the tree itself matches the index


def test_guard_refuses_red_lint(tmp_path):
    r = make(repo(tmp_path, lint="@echo lint is angry; exit 1"), "guard")
    assert r.returncode != 0
    assert "REFUSING: make lint is red" in r.stdout


def test_guard_refuses_red_tests(tmp_path):
    r = make(repo(tmp_path, test="@echo a test failed; exit 1"), "guard")
    assert r.returncode != 0
    assert "REFUSING: make test is red" in r.stdout


def test_guard_skip_test_is_an_escape_that_announces_itself(tmp_path):
    """The documented escape for a design whose suite is too slow for a pre-push hook."""
    root = repo(tmp_path, test="@echo a test failed; exit 1")
    r = make(root, "guard", GUARD_SKIP_TEST="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "GUARD_SKIP_TEST=1" in r.stdout and "SKIPPED deliberately" in r.stdout
    # it drops ONLY the test clause: the tree and lint still refuse
    (root / "README.md").write_text("dirty\n")
    r = make(root, "guard", GUARD_SKIP_TEST="1")
    assert r.returncode != 0 and "REFUSING: unstaged changes" in r.stdout


def test_guard_refuses_outside_a_git_checkout(tmp_path):
    """A template copied by hand: `git diff` failing must not read as "unstaged changes"."""
    root = tmp_path / "nogit"
    root.mkdir()
    shutil.copy(REPO / "Makefile", root / "Makefile")
    with (root / "Makefile").open("a") as f:
        f.write("\nlint:\n\t@true\ntest:\n\t@true\n")
    r = make(root, "guard")
    assert r.returncode != 0
    assert "REFUSING: not a git checkout" in r.stdout


# ------------------------------------------------------------------------- install and remove

def test_install_is_idempotent_and_remove_cleans_up(tmp_path):
    gh = _load_githook()
    root = repo(tmp_path)
    assert gh.state(root) == "absent"
    assert gh.install(root) == 0
    hook = gh.hook_path(root)
    assert hook.is_file() and os.access(hook, os.X_OK) and gh.state(root) == "ours"
    assert gh.install(root) == 0 and gh.state(root) == "ours"     # re-install, not a clobber
    assert gh.remove(root) == 0 and not hook.exists()
    assert gh.remove(root) == 0                                   # removing nothing is fine


def test_install_refuses_to_clobber_a_hook_somebody_wrote(tmp_path):
    """`make init` is idempotent and so is this: a person's own pre-push survives both."""
    gh = _load_githook()
    root = repo(tmp_path)
    hook = gh.hook_path(root)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho mine\n")
    assert gh.state(root) == "foreign"
    assert gh.install(root) == 2 and hook.read_text() == "#!/bin/sh\necho mine\n"
    assert gh.remove(root) == 2 and hook.exists()


def test_hooks_dir_honours_core_hookspath(tmp_path):
    """A clone that redirects its hooks gets the guard there, not in a .git/hooks nobody reads."""
    gh = _load_githook()
    root = repo(tmp_path)
    git(root, "config", "core.hooksPath", "myhooks")
    assert gh.hooks_dir(root) == (root / "myhooks").resolve()
    assert gh.install(root) == 0
    assert (root / "myhooks" / "pre-push").is_file()
    assert not (root / ".git" / "hooks" / "pre-push").exists()


def test_lint_reports_the_hook_as_info_and_never_as_a_failure(tmp_path):
    """Requirement of the decision on #31: INFO, not an invariant — the exit code never moves."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("lint_under_test", REPO / "scripts" / "lint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    gh = _load_githook()
    root = repo(tmp_path)
    assert "not installed" in mod.hook_info(root) and mod.hook_info(root).startswith("INFO:")
    gh.install(root)
    assert "installed" in mod.hook_info(root) and "not installed" not in mod.hook_info(root)
    assert not any(c.__name__ == "hook_info" for c in mod.EXTRA), \
        "hook_info must stay out of EXTRA: an INFO is not a repo invariant"


# ------------------------------------------------------------------------------ the hook, live

@pytest.fixture
def pushable(tmp_path):
    """A repo with the hook installed and a bare remote on a path (no network)."""
    def build(**stubs) -> Path:
        root = repo(tmp_path, **stubs)
        bare = tmp_path / "bare.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env=_env())
        git(root, "remote", "add", "origin", str(bare))
        _load_githook().install(root)
        return root
    return build


def test_the_installed_hook_refuses_a_push_and_names_both_bypasses(pushable):
    """`git push --dry-run` runs pre-push, so the refusal is testable without pushing anything."""
    root = pushable(lint="@echo lint is angry; exit 1")
    r = git(root, "push", "--dry-run", "origin", "main")
    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "REFUSING: make lint is red" in out              # the guard says WHAT is red
    assert "git push --no-verify" in out                    # the hook says how to bypass it
    assert "GUARD_SKIP_TEST=1" in out


def test_no_verify_bypasses_the_hook(pushable):
    root = pushable(lint="@echo lint is angry; exit 1")
    r = git(root, "push", "--no-verify", "origin", "main")
    assert r.returncode == 0, r.stdout + r.stderr


def test_guard_skip_test_reaches_the_hook_through_the_environment(pushable):
    """`GUARD_SKIP_TEST=1 git push` — git hands its environment to the hook, so the escape works."""
    root = pushable(test="@echo a test failed; exit 1")
    assert git(root, "push", "--dry-run", "origin", "main").returncode != 0
    r = subprocess.run(["git", "push", "--dry-run", "origin", "main"], cwd=root,
                       capture_output=True, text=True, env={**_env(), "GUARD_SKIP_TEST": "1"})
    assert r.returncode == 0, r.stdout + r.stderr


# ------------------------------------------------ git's environment: the hook and the suite

# The test clause of the stubbed guard and the probe suite below do what this repo's own tests do
# in their tmp dirs: `git init`, `git add`, `git commit`.
_GIT_WRITES = "git init -q && echo x > f && git add f && git -c user.email=t@t -c user.name=t commit -qm probe"


def _repo_state(root: Path) -> dict[str, str]:
    """What a git write aimed at the wrong repo changes in `root`: refs, local config, worktrees."""
    return {
        "refs": git(root, "for-each-ref", "--format=%(refname) %(objectname)").stdout,
        "config": git(root, "config", "--local", "--list").stdout,
        "worktrees": git(root, "worktree", "list", "--porcelain").stdout,
    }


def test_a_push_from_a_linked_worktree_keeps_the_guard_s_git_calls_out_of_the_repo(pushable,
                                                                                 tmp_path):
    """A push from a linked worktree runs the hook with GIT_DIR=<repo>/.git/worktrees/<name>.

    With that variable in the environment, `git init` and `git commit` in a tmp dir write into
    the repo being pushed: before the hook cleared it, a `make test` run by the hook added commits
    to the pushed branch and set core.bare=true in the repo's config. The hook now removes
    GIT_DIR, GIT_WORK_TREE and GIT_INDEX_FILE before `make guard`.
    """
    probe = tmp_path / "probe"
    probe.mkdir()
    root = pushable(test=f'@cd "{probe}" && {_GIT_WRITES}')
    wt = tmp_path / "w"
    assert git(root, "worktree", "add", "-q", str(wt), "-b", "wt").returncode == 0
    before = _repo_state(root)
    r = git(wt, "push", "--dry-run", "origin", "wt")
    assert _repo_state(root) == before, r.stdout + r.stderr
    assert r.returncode == 0, r.stdout + r.stderr
    assert (probe / ".git").is_dir()      # the stub's commit went to a repo of its own


_PROBE_SUITE = f"""
import subprocess

import pytest


@pytest.fixture(scope="module")
def module_repo(tmp_path_factory):
    # a module-scoped fixture is set up before any function-scoped one
    root = tmp_path_factory.mktemp("module-repo")
    subprocess.run({_GIT_WRITES!r}, shell=True, cwd=root, check=True)
    return root


def test_probe(module_repo, tmp_path):
    subprocess.run({_GIT_WRITES!r}, shell=True, cwd=tmp_path, check=True)
    assert (module_repo / ".git").is_dir() and (tmp_path / ".git").is_dir()
"""


def test_the_suite_removes_git_dir_before_its_first_git_call(tmp_path):
    """`make test` started with GIT_DIR in its environment (by hand, or by a hook installed
    before the hook cleared it) must not write into that repo.

    tests/conftest.py removes GIT_DIR, GIT_WORK_TREE and GIT_INDEX_FILE for the whole session.
    This runs a probe suite under a copy of that conftest, with GIT_DIR pointing at a sentinel
    repo, and checks that the sentinel is unchanged.
    """
    sentinel = tmp_path / "sentinel"
    sentinel.mkdir()
    git(sentinel, "init", "-q", "-b", "main")
    git(sentinel, "commit", "-q", "--allow-empty", "-m", "sentinel")
    suite = tmp_path / "suite"
    suite.mkdir()
    shutil.copy(REPO / "tests" / "conftest.py", suite / "conftest.py")
    (suite / "pytest.ini").write_text("[pytest]\n")
    (suite / "test_probe.py").write_text(_PROBE_SUITE)
    before = _repo_state(sentinel)
    env = {k: v for k, v in _env().items() if not k.startswith(("PYTEST_", "GIT_"))}
    env["GIT_DIR"] = str(sentinel / ".git")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        f"--basetemp={tmp_path / 'probe-tmp'}", str(suite)],
                       cwd=suite, env=env, capture_output=True, text=True, check=False)
    assert _repo_state(sentinel) == before, r.stdout + r.stderr
    assert r.returncode == 0, r.stdout + r.stderr
