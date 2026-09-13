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
