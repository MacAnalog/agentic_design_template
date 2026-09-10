"""`scripts/template_update.py` and `scripts/migrate_v1_to_v2.py` — the two scripts that move a
design between template releases.

Both are exercised against a REAL local template repo (tags and all) built in a temp dir, and a
real design repo cut from it: these scripts are almost entirely git behaviour, and a mocked git
would pin the mock instead of the merge. No network — the template "remote" is a path.

Each script is loaded from a copy inside the temp design repo, because both derive `REPO` from
their own location at import time (`Path(__file__).resolve().parents[1]`) and `sh()` binds that
into a default argument.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def git(*args: str, cwd: Path) -> str:
    r = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                       cwd=cwd, capture_output=True, text=True, check=False)
    assert r.returncode == 0, f"git {' '.join(args)}\n{r.stdout}{r.stderr}"
    return r.stdout


def load_from(repo: Path, name: str):
    """Import `<repo>/scripts/<name>.py` as its own module, so its `REPO` is `repo`."""
    path = repo / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_{repo.name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_template(root: Path, later: dict[str, str] | None = None) -> Path:
    """A template repo tagged v1.00 and v1.01; `later` is what 1.01 writes on top of 1.00."""
    t = root / "template"
    (t / "scripts").mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=t)
    (t / "Makefile").write_text("test:\n\techo one\n")
    (t / "harness.yaml").write_text("package: design\n")
    git("add", "-A", cwd=t)
    git("commit", "-qm", "1.00", cwd=t)
    git("tag", "v1.00", cwd=t)
    for rel, text in (later or {"Makefile": "test:\n\techo TWO (template 1.01)\n"}).items():
        p = t / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git("add", "-A", cwd=t)
    git("commit", "-qm", "1.01", cwd=t)
    git("tag", "v1.01", cwd=t)
    return t


def make_design(root: Path, files: dict[str, str], *, version: str = "1.00",
                scripts: tuple[str, ...] = ("template_update",)) -> Path:
    d = root / "design"
    (d / "scripts").mkdir(parents=True)
    for name in scripts:
        shutil.copy(SCRIPTS / f"{name}.py", d / "scripts" / f"{name}.py")
    git("init", "-q", "-b", "main", cwd=d)
    (d / "harness.yaml").write_text("package: design\n")
    for rel, text in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    (d / ".sx").mkdir()
    (d / ".sx" / "template-version").write_text(version + "\n")
    git("add", "-A", cwd=d)
    git("commit", "-qm", "cut from the template", cwd=d)
    return d


# ------------------------------------------------------------------ AT-02 --------------

def test_a_conflicting_update_does_not_advance_the_recorded_version(tmp_path):
    """AT-02: the version file was written BEFORE the conflict scan, so an update that left
    conflict markers still recorded the new release — and the next update, believing the design is
    already there, never offers the rejected change again."""
    tmpl = make_template(tmp_path)
    design = make_design(tmp_path, {"Makefile": "test:\n\techo the design's own line\n"})
    tu = load_from(design, "template_update")
    tu.URL = str(tmpl)

    rc = tu.update(None)
    assert rc == 1, "a conflicted apply must exit non-zero"
    assert (design / ".sx" / "template-version").read_text().strip() == "1.00", \
        "the release was recorded although its change did not land"


def test_a_clean_update_does_advance_the_recorded_version(tmp_path):
    """The other half: nothing may stop recording a release that actually applied."""
    tmpl = make_template(tmp_path)
    design = make_design(tmp_path, {"Makefile": "test:\n\techo one\n"})   # untouched: merges clean
    tu = load_from(design, "template_update")
    tu.URL = str(tmpl)

    assert tu.update(None) == 0
    assert (design / ".sx" / "template-version").read_text().strip() == "1.01"


def test_a_new_file_that_would_not_apply_is_not_reported_as_skipped(tmp_path):
    """AT-02, second half: `skipped — this design does not carry the file the change edits` was
    printed for ANY failed apply on an absent target, including a file the release ADDS."""
    tmpl = make_template(tmp_path, later={"lab/new/thing.py": "print('new in 1.01')\n"})
    # the design carries a FILE where 1.01 wants a directory: the target itself does not exist, so
    # `exists` is False and the failed apply took the "you do not carry this file" branch
    design = make_design(tmp_path, {"lab/new": "not a directory\n"})
    tu = load_from(design, "template_update")
    tu.URL = str(tmpl)

    rc = tu.update(None)
    rows = {r[0]: r[1] for r in tu._apply("1.00", "1.01", [".", ":!design", *tu.EXCLUDE])}
    assert rows.get("lab/new/thing.py") == "REJECTED", rows
    assert rc == 1
    assert (design / ".sx" / "template-version").read_text().strip() == "1.00"


# ------------------------------------------------------------------ AT-03 --------------

def test_migrate_dry_run_changes_nothing_in_the_repo(tmp_path):
    """AT-03: `main()` called `have_target()` before consulting `--dry-run`, and that adds the
    `template` remote and runs `git fetch --tags --force` — a dry run that writes refs (and can
    move a tag) into the repo it claims not to touch."""
    tmpl = make_template(tmp_path)
    git("tag", "v2.00", cwd=tmpl)
    design = make_design(tmp_path, {"Makefile": "test:\n\techo one\n"},
                         scripts=("template_update", "migrate_v1_to_v2"))
    # the remote already exists and points at the local template: the fetch would work, so what
    # this test measures is whether a dry run performs it at all
    git("remote", "add", "template", str(tmpl), cwd=design)
    before = git("rev-parse", "HEAD", cwd=design)

    mig = load_from(design, "migrate_v1_to_v2")
    mig.URL = str(tmpl)
    rc = mig.main(["--dry-run"])

    assert rc == 0
    assert git("tag", "--list", cwd=design).split() == [], \
        "the dry run fetched tags into the design repo"
    # `__pycache__` is this test importing the script from inside the repo, not the migration
    left = [ln for ln in git("status", "--porcelain", cwd=design).splitlines()
            if "__pycache__" not in ln]
    assert left == [], f"the dry run left changes in the tree: {left}"
    assert git("rev-parse", "HEAD", cwd=design) == before
    assert (design / ".sx" / "template-version").read_text().strip() == "1.00"


def test_migrate_dry_run_does_not_add_the_template_remote(tmp_path):
    """The same rule for a design that has never fetched the template: a dry run adds no remote."""
    tmpl = make_template(tmp_path)
    git("tag", "v2.00", cwd=tmpl)
    design = make_design(tmp_path, {"Makefile": "test:\n\techo one\n"},
                         scripts=("template_update", "migrate_v1_to_v2"))
    mig = load_from(design, "migrate_v1_to_v2")
    mig.URL = str(tmpl)

    rc = mig.main(["--dry-run"])
    assert rc == 0
    assert git("remote", cwd=design).split() == [], "the dry run added a git remote"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
