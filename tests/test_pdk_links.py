"""The `pdk-<id>` link set: `scripts/pdk_links.py`, `make init` / `make skills-update`, `make lint`.

Hermetic: every case runs in a temporary directory against a stub `sx-link` that appends its
arguments to a log, so no test needs the library checked out.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TEMPLATE_YAML = (REPO / "harness.yaml").read_text()


def _mod(rel: str):
    path = REPO / rel
    spec = importlib.util.spec_from_file_location(path.stem + "_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pdk_links = _mod("scripts/pdk_links.py")


@pytest.fixture(autouse=True)
def _no_private_library(monkeypatch):
    """A person's own `$SX_KIT_SKILLS` must not reach these cases; the ones that need it set it."""
    monkeypatch.delenv(pdk_links.KIT_SKILLS_ENV, raising=False)


def _with_pdk(line: str, base: str = TEMPLATE_YAML) -> str:
    """This checkout's harness.yaml with its `pdk:` line replaced by `line` ("" drops it) and on
    the open lane: a top-level `lane:` line is removed, so a design on `lane: bridge` gets the same
    fixture as the template, and a case that wants the bridge lane appends the line itself. A
    design that has not added `pdk:` yet (CHANGELOG v2.14, Taking it, step 2) gets the line
    appended, so these tests do not depend on that step."""
    open_lane = re.sub(r"^lane:.*\n?", "", base, flags=re.MULTILINE)
    out, n = re.subn(r"^pdk:.*$", line, open_lane, count=1, flags=re.MULTILINE)
    if n == 0:
        out = open_lane.rstrip("\n") + "\n" + (line + "\n" if line else "")
    return out


@pytest.mark.parametrize(
    ("line", "want"),
    [
        ('pdk: ""   # declare it', ""),
        ("pdk: ihp-sg13g2", "ihp-sg13g2"),
        ('pdk: "ihp-sg13g2"   # the open kit', "ihp-sg13g2"),
        ("pdk: 'ihp-sg13g2'", "ihp-sg13g2"),
        ("pdk: ihp-sg13g2   # the open kit", "ihp-sg13g2"),
        ("pdk:", ""),
        ("pdk: ~", ""),
        ("# pdk: ihp-sg13g2", ""),
        ("", ""),
    ],
)
def test_declared_pdk_agrees_with_the_harness_loader(tmp_path, line, want):
    from spicexplorer_harness import load

    text = _with_pdk(line)
    assert pdk_links.declared_pdk(text) == want
    (tmp_path / "harness.yaml").write_text(text)
    assert str(load(tmp_path).pdk or "") == want


def test_a_nested_pdk_key_is_not_the_declaration():
    assert pdk_links.declared_pdk("name: x\nlane_opts:\n  pdk: ihp-sg13g2\n") == ""


def _library(root: Path, *, sets: tuple[str, ...] = ("design",), fail: str = "") -> Path:
    """A stand-in `.sx/skills`: link sets named `sets` and an `sx-link` that logs its argv and
    exits 1 when its argv contains `fail`."""
    lib = root / ".sx" / "skills"
    (lib / "linksets").mkdir(parents=True, exist_ok=True)
    for name in sets:
        (lib / "linksets" / f"{name}.txt").write_text("skills/x\n")
    tool = lib / "bin" / "sx-link"
    tool.parent.mkdir(parents=True, exist_ok=True)
    log = lib / "argv.log"
    rc = (
        f'case "$*" in *{fail}*) echo "MISSING  .claude/skills/{fail}"; exit 1;; esac\n'
        if fail
        else ""
    )
    tool.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n{rc}exit 0\n')
    tool.chmod(0o755)
    return log


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.is_file() else []


def test_nothing_is_linked_without_a_declared_pdk(tmp_path, capsys):
    (tmp_path / "harness.yaml").write_text(_with_pdk(""))
    log = _library(tmp_path, sets=("design", "pdk-ihp-sg13g2"))
    assert pdk_links.main(tmp_path) == 0
    assert _calls(log) == [] and capsys.readouterr().out == ""


def test_a_declared_pdk_links_its_set(tmp_path):
    (tmp_path / "harness.yaml").write_text(_with_pdk("pdk: ihp-sg13g2"))
    log = _library(tmp_path, sets=("design", "pdk-ihp-sg13g2"))
    assert pdk_links.main(tmp_path) == 0
    assert _calls(log) == [f"{tmp_path} --set pdk-ihp-sg13g2"]


def test_a_declared_pdk_the_library_has_no_set_for_links_nothing(tmp_path, capsys):
    (tmp_path / "harness.yaml").write_text(_with_pdk("pdk: some-other-kit"))
    log = _library(tmp_path, sets=("design", "pdk-ihp-sg13g2"))
    assert pdk_links.main(tmp_path) == 0
    assert _calls(log) == []
    assert "no linksets/pdk-some-other-kit.txt" in capsys.readouterr().out


def test_an_id_that_is_not_a_file_name_is_not_used_as_one(tmp_path):
    (tmp_path / ".sx" / "skills" / "linksets").mkdir(parents=True)
    assert pdk_links.linkset(tmp_path, "../design") is None
    assert pdk_links.linkset(tmp_path, "") is None


def test_init_and_skills_update_run_the_same_link_step():
    """Both recipes expand `$(LINK)`: the `design` set, then scripts/pdk_links.py."""
    env = {k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MAKELEVEL", "MFLAGS")}
    for target in ("init", "skills-update"):
        r = subprocess.run(
            ["make", "-n", target, "SX_ROOT=/nonexistent"],
            cwd=REPO,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        link = [ln for ln in r.stdout.splitlines() if "sx-link" in ln]
        assert link and all(
            "--set design && " in ln and ln.endswith("scripts/pdk_links.py") for ln in link
        ), (target, r.stdout)


def _lint_repo(tmp_path: Path, pdk_line: str, fail: str = "", lane: str = ""):
    from spicexplorer_harness import load
    from spicexplorer_harness.lint import Lint

    text = _with_pdk(pdk_line) + (f"lane: {lane}\n" if lane else "")
    (tmp_path / "harness.yaml").write_text(text)
    marker = tmp_path / ".sx/platform/packages/spicexplorer-harness/pyproject.toml"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("")
    log = _library(tmp_path, sets=("design", "pdk-ihp-sg13g2"), fail=fail)
    mod = _mod("scripts/lint.py")
    L = Lint(load(tmp_path))
    mod.sx_links(L)
    return L, _calls(log)


def test_lint_checks_the_pdk_set_after_the_design_set(tmp_path):
    L, calls = _lint_repo(tmp_path, "pdk: ihp-sg13g2")
    assert L.fails == []
    assert calls == [f"{tmp_path} --set design --check", f"{tmp_path} --set pdk-ihp-sg13g2 --check"]


def test_lint_checks_only_the_design_set_without_a_declared_pdk(tmp_path):
    L, calls = _lint_repo(tmp_path, 'pdk: ""')
    assert L.fails == [] and calls == [f"{tmp_path} --set design --check"]


def test_lint_reports_a_missing_pdk_link_with_make_init_as_the_fix(tmp_path):
    L, _ = _lint_repo(tmp_path, "pdk: ihp-sg13g2", fail="pdk-ihp-sg13g2")
    assert len(L.fails) == 1, L.fails
    assert "MISSING  .claude/skills/pdk-ihp-sg13g2" in L.fails[0] and "make init" in L.fails[0]


# --- one PDK id (spicexplorer_harness.fleet.pdk_id) --------------------------------------------


def test_a_registry_token_links_the_set_of_its_ratified_id(tmp_path):
    """`ihp130` is the registry token of the open kit whose set is `pdk-ihp-sg13g2`."""
    (tmp_path / "harness.yaml").write_text(_with_pdk("pdk: ihp130"))
    log = _library(tmp_path, sets=("design", "pdk-ihp-sg13g2"))
    assert pdk_links.main(tmp_path) == 0
    assert _calls(log) == [f"{tmp_path} --set pdk-ihp-sg13g2"]


def test_the_ratified_id_comes_from_the_harness_not_a_copy():
    from spicexplorer_harness.fleet import PDK_IDS, pdk_id

    for token, rid in PDK_IDS.items():
        assert pdk_links.ratified(token) == pdk_id(token) == rid
    assert pdk_links.ratified("some-other-kit") == "some-other-kit"
    assert pdk_links.ratified("") == ""


def test_spellings_put_the_ratified_id_first_then_the_declared_one_then_registry_tokens():
    assert pdk_links.spellings("ihp130") == ["ihp-sg13g2", "ihp130"]
    assert pdk_links.spellings("ihp-sg13g2") == ["ihp-sg13g2", "ihp130"]
    assert pdk_links.spellings("../x") == []


def test_without_an_importable_harness_the_fleet_file_under_sx_platform_is_read(
    tmp_path, monkeypatch
):
    """`make init` runs the script before `uv sync`: the harness is then only a file."""
    fleet = tmp_path / pdk_links._FLEET
    fleet.parent.mkdir(parents=True)
    fleet.write_text(
        'PDK_IDS = {"tok1": "kit-one"}\n\ndef pdk_id(p):\n    return PDK_IDS.get(p, p)\n'
    )
    monkeypatch.setitem(sys.modules, "spicexplorer_harness", None)  # import fails
    assert pdk_links.ratified("tok1", tmp_path) == "kit-one"
    assert pdk_links.spellings("kit-one", tmp_path) == ["kit-one", "tok1"]
    assert pdk_links.ratified("tok1", tmp_path / "nowhere") == "tok1"  # unreadable: as written


def test_lint_warns_on_a_registry_token_and_names_the_ratified_id(tmp_path):
    L, _ = _lint_repo(tmp_path, "pdk: ihp130")
    assert L.fails == []
    assert any("ihp130" in w and "ihp-sg13g2" in w for w in L.warns), L.warns


# --- the private per-kit library ($SX_KIT_SKILLS) ----------------------------------------------


def _private(root: Path, entries: str = "skills/pdk-kitx\n") -> Path:
    lib = root / "private-kit-lib"
    (lib / "linksets").mkdir(parents=True)
    (lib / "linksets" / "pdk.txt").write_text("# the kit knowledge base\n" + entries)
    (lib / "skills" / "pdk-kitx").mkdir(parents=True)
    return lib


def _git(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)


def test_sx_kit_skills_links_the_private_pdk_set_and_keeps_it_out_of_commits(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo)
    (repo / "harness.yaml").write_text(_with_pdk("pdk: kitx") + "lane: bridge\n")
    log = _library(repo)
    lib = _private(tmp_path)
    assert pdk_links.main(repo, env={pdk_links.KIT_SKILLS_ENV: str(lib)}) == 0
    assert _calls(log) == [f"{repo} --library {lib} --set pdk"]
    exclude = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert "/.claude/skills/pdk-kitx" in exclude
    # a second run adds nothing twice
    pdk_links.main(repo, env={pdk_links.KIT_SKILLS_ENV: str(lib)})
    again = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert again.count("/.claude/skills/pdk-kitx") == 1
    # the link itself (the stub sx-link makes none): git must not offer it for a commit
    link = repo / ".claude" / "skills" / "pdk-kitx"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(lib / "skills" / "pdk-kitx")
    r = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--", ".claude"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert r.stdout == ""


def test_a_private_library_without_a_pdk_set_is_an_error(tmp_path, capsys):
    (tmp_path / "harness.yaml").write_text(_with_pdk("pdk: kitx"))
    log = _library(tmp_path)
    empty = tmp_path / "not-a-library"
    empty.mkdir()
    assert pdk_links.main(tmp_path, env={pdk_links.KIT_SKILLS_ENV: str(empty)}) == 2
    assert "has no linksets/pdk.txt" in capsys.readouterr().out
    assert _calls(log) == []


def test_link_paths_follow_sx_link():
    assert pdk_links.link_paths(["skills/a", "agents/b", "bogus"]) == [
        ".claude/skills/a",
        ".claude/agents/b.md",
    ]


def test_lint_checks_the_private_library_when_sx_kit_skills_is_set(tmp_path, monkeypatch):
    lib = _private(tmp_path / "elsewhere")
    monkeypatch.setenv(pdk_links.KIT_SKILLS_ENV, str(lib))
    L, calls = _lint_repo(tmp_path, "pdk: kitx", lane="bridge")
    assert L.fails == []
    assert calls[-1] == f"{tmp_path} --library {lib} --set pdk --check"


def test_lint_fails_when_the_private_library_link_is_missing(tmp_path, monkeypatch):
    lib = _private(tmp_path / "elsewhere")
    monkeypatch.setenv(pdk_links.KIT_SKILLS_ENV, str(lib))
    L, _ = _lint_repo(tmp_path, "pdk: kitx", fail="--library", lane="bridge")
    assert len(L.fails) == 1 and "make init" in L.fails[0], L.fails


def test_lint_fails_on_a_bridge_lane_kit_with_no_skill_linked(tmp_path):
    L, _ = _lint_repo(tmp_path, "pdk: kitx", lane="bridge")
    assert len(L.fails) == 1, L.fails
    assert pdk_links.KIT_SKILLS_ENV in L.fails[0] and "make init" in L.fails[0]


def test_lint_accepts_a_bridge_lane_kit_skill_linked_by_hand(tmp_path):
    target = tmp_path / "kit-skill"
    target.mkdir()
    link = tmp_path / ".claude" / "skills" / "pdk-kitx"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    L, _ = _lint_repo(tmp_path, "pdk: kitx", lane="bridge")
    assert L.fails == []


def test_lint_needs_no_private_library_on_the_open_lane(tmp_path):
    L, _ = _lint_repo(tmp_path, "pdk: kitx")
    assert pdk_links.declared((tmp_path / "harness.yaml").read_text(), "lane") == ""
    assert L.fails == []


def test_the_fixture_is_on_the_open_lane_whatever_this_checkout_declares():
    """A design on `lane: bridge` runs these tests against its own harness.yaml."""
    bridge = _with_pdk("pdk: kitx") + "lane: bridge   # a commercial kit\n"
    text = _with_pdk("pdk: other", base=bridge)
    assert pdk_links.declared(text, "lane") == "" and pdk_links.declared_pdk(text) == "other"
