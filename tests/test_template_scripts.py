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
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def git(*args: str, cwd: Path) -> str:
    r = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, f"git {' '.join(args)}\n{r.stdout}{r.stderr}"
    return r.stdout


def load_from(repo: Path, name: str):
    """Import `<repo>/scripts/<name>.py` as its own module, so its `REPO` is `repo`."""
    path = repo / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_{repo.name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_template(
    root: Path, later: dict[str, str] | None = None, first: dict[str, str] | None = None
) -> Path:
    """A template repo tagged v1.00 and v1.01; `first` is what 1.00 holds besides its `Makefile`
    and `harness.yaml`, `later` what 1.01 writes on top of 1.00."""
    t = root / "template"
    (t / "scripts").mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=t)
    (t / "Makefile").write_text("test:\n\techo one\n")
    (t / "harness.yaml").write_text("package: design\n")
    for rel, text in (first or {}).items():
        (t / rel).parent.mkdir(parents=True, exist_ok=True)
        (t / rel).write_text(text)
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


def make_design(
    root: Path,
    files: dict[str, str],
    *,
    version: str = "1.00",
    scripts: tuple[str, ...] = ("template_update",),
) -> Path:
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
    assert (design / ".sx" / "template-version").read_text().strip() == "1.00", (
        "the release was recorded although its change did not land"
    )


def test_a_clean_update_does_advance_the_recorded_version(tmp_path):
    """The other half: nothing may stop recording a release that actually applied."""
    tmpl = make_template(tmp_path)
    design = make_design(tmp_path, {"Makefile": "test:\n\techo one\n"})  # untouched: merges clean
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


def test_a_template_dut_change_offers_no_hunk_to_the_design_dut(tmp_path):
    """#63: `PKG_EXCLUDE` held `:!dut.py`, a pathspec git resolves against the repo root, not the
    `--relative=design/` prefix, so the template's `design/dut.py` hunk still reached the design's
    own `<package>/dut.py`. The rest of the package must still arrive."""
    first = {"design/dut.py": "STUB = 1\n", "design/sim.py": "LANE = 1\n"}
    later = {"design/dut.py": "STUB = 2\n", "design/sim.py": "LANE = 2\n"}
    tmpl = make_template(tmp_path, later=later, first=first)
    design = make_design(
        tmp_path,
        {
            "harness.yaml": "package: cell\n",
            "cell/dut.py": "STUB = 1\n",
            "cell/sim.py": "LANE = 1\n",
        },
    )
    tu = load_from(design, "template_update")
    tu.URL = str(tmpl)

    assert tu.update(None) == 0
    assert (design / "cell" / "dut.py").read_text() == "STUB = 1\n", (
        "the template's dut.py hunk landed"
    )
    assert (design / "cell" / "sim.py").read_text() == "LANE = 2\n"


def test_an_update_that_changes_a_signed_scorer_says_to_re_certify(tmp_path, capsys):
    """A release that edits the scorer a committed scorecard hashes (`provenance.script`) leaves
    that card's script_sha stale: the update says so, and names the card and the way to defer."""
    tmpl = make_template(
        tmp_path,
        first={"design/metrics.py": "VALUE = 1\n"},
        later={"design/metrics.py": "VALUE = 2\n"},
    )
    card = {
        "scorecard": {"gain_db": 60},
        "provenance": {"script": "amp/metrics.py", "script_sha": "0" * 64},
    }
    other = {"scorecard": {}, "provenance": {"script": "amp/bench.py", "script_sha": "1" * 64}}
    design = make_design(
        tmp_path,
        {
            "amp/metrics.py": "VALUE = 1\n",
            "decks/reference/scorecard.json": json.dumps(card),
            "signoff/schematic/scorecard.json": json.dumps(other),
        },
    )
    (design / "harness.yaml").write_text("package: amp\n")
    git("commit", "-qam", "renamed", cwd=design)
    tu = load_from(design, "template_update")
    tu.URL = str(tmpl)

    assert tu.signed_scorers() == {
        "amp/metrics.py": ["decks/reference/scorecard.json"],
        "amp/bench.py": ["signoff/schematic/scorecard.json"],
    }
    assert tu.update(None) == 0
    out = capsys.readouterr().out
    assert (design / "amp" / "metrics.py").read_text() == "VALUE = 2\n"
    assert "WARNING: amp/metrics.py is the scorer decks/reference/scorecard.json" in out, out
    assert "re-certify" in out and "git checkout HEAD -- amp/metrics.py" in out
    assert "amp/bench.py" not in out, "a scorer the release does not touch is not named"


def test_an_update_that_touches_no_signed_scorer_prints_no_warning(tmp_path, capsys):
    tmpl = make_template(tmp_path)
    card = {"provenance": {"script": "design/metrics.py", "script_sha": "0" * 64}}
    design = make_design(
        tmp_path,
        {"Makefile": "test:\n\techo one\n", "decks/reference/scorecard.json": json.dumps(card)},
    )
    tu = load_from(design, "template_update")
    tu.URL = str(tmpl)
    assert tu.update(None) == 0
    assert "WARNING" not in capsys.readouterr().out


def test_the_update_runs_the_target_releases_own_script(tmp_path):
    """The update ran the design's own (older) copy of the script, so a check a release adds to
    `update()` (v2.16's signed-scorer warning) was skipped on the very update that brought it:
    2.14 -> 2.16 merged a signed `metrics.py` and printed no WARNING. The run now hands over to the
    target release's script, which therefore prints what only that release's script knows."""
    current = (SCRIPTS / "template_update.py").read_text()
    newer = current.replace('"NOW: read every merged file', '"NOW (release 1.01): read every')
    assert newer != current
    tmpl = make_template(
        tmp_path,
        first={"scripts/template_update.py": current},
        later={"scripts/template_update.py": newer},
    )
    design = make_design(tmp_path, {"Makefile": "test:\n\techo one\n"})
    git("remote", "add", "template", str(tmpl), cwd=design)

    r = subprocess.run(
        [sys.executable, "scripts/template_update.py", "update"],
        cwd=design,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOW (release 1.01)" in r.stdout, "the design's own copy ran the update"
    assert r.stdout.count("template 1.00 -> 1.01") == 1, "the update ran twice"
    assert (design / "scripts" / "template_update.py").read_text() == newer
    assert (design / ".sx" / "template-version").read_text().strip() == "1.01"
    untracked = git("ls-files", "--others", "--", "scripts", cwd=design)
    assert untracked == "", f"the handed-over copy was left behind: {untracked}"


@pytest.mark.parametrize("base", ["tag", "recorded-commit"])
def test_a_design_copy_that_differs_from_its_base_script_runs_the_update_itself(tmp_path, base):
    """The handoff ran whenever the target's script differed from the design's copy, also when the
    design's copy is NEWER than the target's (taken on purpose, as a *Taking it* step says): a
    target release that predates `.sx/template-commit` then merged from the tag again and
    conflicted. The run is handed over only when the design's copy is its base commit's script."""
    current = (SCRIPTS / "template_update.py").read_text()
    older = current.replace("keep a design in step", "keep a design in step (release 1.00)")
    target = older.replace('"NOW: read every merged file', '"NOW (release 1.01): read every')
    assert current != older != target
    tmpl = make_template(
        tmp_path,
        first={"scripts/template_update.py": older},
        later={"scripts/template_update.py": target},
    )
    ref = "v1.00"
    if base == "recorded-commit":
        # an untagged commit after v1.00 the design was cut from, script unchanged
        git("tag", "-d", "v1.01", cwd=tmpl)
        git("reset", "-q", "--hard", "v1.00", cwd=tmpl)
        (tmpl / "Makefile").write_text("test:\n\techo cut\n")
        git("commit", "-qam", "cut", cwd=tmpl)
        ref = git("rev-parse", "HEAD", cwd=tmpl).strip()
        (tmpl / "scripts" / "template_update.py").write_text(target)
        git("commit", "-qam", "1.01", cwd=tmpl)
        git("tag", "v1.01", cwd=tmpl)
    makefile = "test:\n\techo cut\n" if base == "recorded-commit" else "test:\n\techo one\n"
    design = make_design(tmp_path, {"Makefile": makefile})
    if base == "recorded-commit":
        (design / ".sx" / "template-commit").write_text(ref + "\n")
        git("add", "-A", cwd=design)
        git("commit", "-qm", "record the cut", cwd=design)
    git("remote", "add", "template", str(tmpl), cwd=design)

    r = subprocess.run(
        [sys.executable, "scripts/template_update.py", "update"],
        cwd=design,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "running v1.01's" not in r.stdout, "the run was handed to the target's script"
    assert "NOW (release 1.01)" not in r.stdout
    assert f"base: {ref}" in r.stdout, r.stdout
    assert (design / ".sx" / "template-version").read_text().strip() == "1.01"


# ------------------------------------------------- a design cut between two tags --------------


def make_template_with_untagged_cut(root: Path) -> tuple[Path, str]:
    """v1.00, then an UNTAGGED commit that edits the Makefile's line, then v1.01 editing the same
    line again. Returns the template and the untagged commit's sha."""
    tmpl = make_template(root, later={"Makefile": "test:\n\techo two\n"})
    git("tag", "-d", "v1.01", cwd=tmpl)
    cut = git("rev-parse", "HEAD", cwd=tmpl).strip()
    (tmpl / "Makefile").write_text("test:\n\techo three (template 1.01)\n")
    git("commit", "-qam", "1.01", cwd=tmpl)
    git("tag", "v1.01", cwd=tmpl)
    return tmpl, cut


def test_a_design_cut_from_an_untagged_commit_merges_from_that_commit(tmp_path):
    """The base was always the tag `.sx/template-version` names. A design cut from a commit after
    that tag already carries the changes up to the commit, so a diff from the tag re-applied them
    and conflicted on every file they touched although the design had edited none of them."""
    tmpl, cut = make_template_with_untagged_cut(tmp_path)
    design = make_design(tmp_path, {"Makefile": "test:\n\techo two\n"}, version="1.00")
    (design / ".sx" / "template-commit").write_text(cut + "\n")
    tu = load_from(design, "template_update")
    tu.URL = str(tmpl)

    assert tu.update(None) == 0
    assert (design / "Makefile").read_text() == "test:\n\techo three (template 1.01)\n"
    assert (design / ".sx" / "template-version").read_text().strip() == "1.01"
    v101 = git("rev-parse", "v1.01^{commit}", cwd=tmpl).strip()
    assert (design / ".sx" / "template-commit").read_text().strip() == v101


def test_without_a_recorded_commit_the_tag_stays_the_base(tmp_path):
    """The fallback: no `.sx/template-commit`, the base is `v<recorded>` as before, so the same cut
    conflicts — the failure the recorded commit removes."""
    tmpl, _ = make_template_with_untagged_cut(tmp_path)
    design = make_design(tmp_path, {"Makefile": "test:\n\techo two\n"}, version="1.00")
    tu = load_from(design, "template_update")
    tu.URL = str(tmpl)

    assert tu.update(None) == 1
    assert (design / ".sx" / "template-version").read_text().strip() == "1.00"
    assert not (design / ".sx" / "template-commit").exists()


def test_a_clean_update_records_the_release_commit(tmp_path):
    """After any landed release the base is exact, whether or not the cut recorded a commit."""
    tmpl = make_template(tmp_path)
    design = make_design(tmp_path, {"Makefile": "test:\n\techo one\n"})
    tu = load_from(design, "template_update")
    tu.URL = str(tmpl)

    assert tu.update(None) == 0
    v101 = git("rev-parse", "v1.01^{commit}", cwd=tmpl).strip()
    assert (design / ".sx" / "template-commit").read_text().strip() == v101


@pytest.mark.parametrize("which", ["unrelated", "after-target", "garbage"])
def test_a_recorded_commit_outside_the_release_range_stops_the_update(tmp_path, which):
    """A wrong base is the defect, so a recorded commit that is not between `v<recorded>` and the
    target release stops the update with the file named; it never falls back to the tag silently."""
    tmpl, _ = make_template_with_untagged_cut(tmp_path)
    if which == "after-target":
        (tmpl / "Makefile").write_text("test:\n\techo four\n")
        git("commit", "-qam", "after 1.01", cwd=tmpl)
        sha = git("rev-parse", "HEAD", cwd=tmpl).strip()
    elif which == "unrelated":
        other = tmp_path / "other"
        other.mkdir()
        git("init", "-q", "-b", "main", cwd=other)
        (other / "x").write_text("x\n")
        git("add", "-A", cwd=other)
        git("commit", "-qm", "x", cwd=other)
        sha = git("rev-parse", "HEAD", cwd=other).strip()
    else:
        sha = "not-a-sha"
    design = make_design(tmp_path, {"Makefile": "test:\n\techo two\n"}, version="1.00")
    (design / ".sx" / "template-commit").write_text(sha + "\n")
    tu = load_from(design, "template_update")
    tu.URL = str(tmpl)
    if which == "after-target":  # make the commit reachable in the design, as a fetch of main would
        tu.fetch()
        git("fetch", "-q", "template", "main", cwd=design)

    with pytest.raises(SystemExit, match="template-commit"):
        tu.update(None)
    assert (design / "Makefile").read_text() == "test:\n\techo two\n"
    assert (design / ".sx" / "template-version").read_text().strip() == "1.00"


# ------------------------------------------------------------------ AT-03 --------------


def test_migrate_dry_run_changes_nothing_in_the_repo(tmp_path):
    """AT-03: `main()` called `have_target()` before consulting `--dry-run`, and that adds the
    `template` remote and runs `git fetch --tags --force` — a dry run that writes refs (and can
    move a tag) into the repo it claims not to touch."""
    tmpl = make_template(tmp_path)
    git("tag", "v2.00", cwd=tmpl)
    design = make_design(
        tmp_path,
        {"Makefile": "test:\n\techo one\n"},
        scripts=("template_update", "migrate_v1_to_v2"),
    )
    # the remote already exists and points at the local template: the fetch would work, so what
    # this test measures is whether a dry run performs it at all
    git("remote", "add", "template", str(tmpl), cwd=design)
    before = git("rev-parse", "HEAD", cwd=design)

    mig = load_from(design, "migrate_v1_to_v2")
    mig.URL = str(tmpl)
    rc = mig.main(["--dry-run"])

    assert rc == 0
    assert git("tag", "--list", cwd=design).split() == [], (
        "the dry run fetched tags into the design repo"
    )
    # `__pycache__` is this test importing the script from inside the repo, not the migration
    left = [
        ln
        for ln in git("status", "--porcelain", cwd=design).splitlines()
        if "__pycache__" not in ln
    ]
    assert left == [], f"the dry run left changes in the tree: {left}"
    assert git("rev-parse", "HEAD", cwd=design) == before
    assert (design / ".sx" / "template-version").read_text().strip() == "1.00"


def test_migrate_dry_run_does_not_add_the_template_remote(tmp_path):
    """The same rule for a design that has never fetched the template: a dry run adds no remote."""
    tmpl = make_template(tmp_path)
    git("tag", "v2.00", cwd=tmpl)
    design = make_design(
        tmp_path,
        {"Makefile": "test:\n\techo one\n"},
        scripts=("template_update", "migrate_v1_to_v2"),
    )
    mig = load_from(design, "migrate_v1_to_v2")
    mig.URL = str(tmpl)

    rc = mig.main(["--dry-run"])
    assert rc == 0
    assert git("remote", cwd=design).split() == [], "the dry run added a git remote"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
