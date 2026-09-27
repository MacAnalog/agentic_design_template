"""The `pdk-<id>` link set: `scripts/pdk_links.py`, `make init` / `make skills-update`, `make lint`.

Hermetic: every case runs in a temporary directory against a stub `sx-link` that appends its
arguments to a log, so no test needs the library checked out.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
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


def _with_pdk(line: str) -> str:
    """The template's harness.yaml with its `pdk:` line replaced by `line` ("" drops it)."""
    out, n = re.subn(r"^pdk:.*$", line, TEMPLATE_YAML, count=1, flags=re.M)
    assert n == 1, "the template's harness.yaml has no top-level pdk: line"
    return out


@pytest.mark.parametrize(("line", "want"), [
    ('pdk: ""   # declare it', ""),
    ("pdk: ihp-sg13g2", "ihp-sg13g2"),
    ('pdk: "ihp-sg13g2"   # the open kit', "ihp-sg13g2"),
    ("pdk: 'ihp-sg13g2'", "ihp-sg13g2"),
    ("pdk: ihp-sg13g2   # the open kit", "ihp-sg13g2"),
    ("pdk:", ""),
    ("pdk: ~", ""),
    ("# pdk: ihp-sg13g2", ""),
    ("", ""),
])
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
    rc = (f'case "$*" in *{fail}*) echo "MISSING  .claude/skills/{fail}"; exit 1;; esac\n'
          if fail else "")
    tool.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n{rc}exit 0\n')
    tool.chmod(0o755)
    return log


def _calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.is_file() else []


def test_nothing_is_linked_without_a_declared_pdk(tmp_path, capsys):
    (tmp_path / "harness.yaml").write_text(TEMPLATE_YAML)
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
        r = subprocess.run(["make", "-n", target, "SX_ROOT=/nonexistent"], cwd=REPO,
                           capture_output=True, text=True, env=env, check=False)
        link = [ln for ln in r.stdout.splitlines() if "sx-link" in ln]
        assert link and all("--set design && " in ln and ln.endswith("scripts/pdk_links.py")
                            for ln in link), (target, r.stdout)


def _lint_repo(tmp_path: Path, pdk_line: str, fail: str = ""):
    from spicexplorer_harness import load
    from spicexplorer_harness.lint import Lint

    (tmp_path / "harness.yaml").write_text(_with_pdk(pdk_line))
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
