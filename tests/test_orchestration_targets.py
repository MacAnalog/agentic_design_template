"""`make size` and `make layout-flow`: thin calls of two orchestration workflows.

Hermetic: `SX_ROOT` is a temporary directory whose orchestration "venv" interpreter is a stub that
writes its argv, one argument per line, and exits 0. What is checked is the command each target
builds; the workflows themselves are the orchestration repo's to test.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _layout_lane():
    path = REPO / "scripts" / "layout_lane.py"
    spec = importlib.util.spec_from_file_location("layout_lane_targets_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


layout_lane = _layout_lane()
# This checkout's `lane:`: the template ships it absent; a design on `lane: bridge` runs this file too
LANE = layout_lane.declared_lane(REPO)


def _sx_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "workspace"
    py = root / "spicexplorer-orchestration" / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    log = tmp_path / "argv"
    py.write_text(f'#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done > "{log}"\nexit 0\n')
    py.chmod(0o755)
    return root, log


def _make(*args: str, sx_root: Path | None) -> subprocess.CompletedProcess:
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in (
            "MAKEFLAGS",
            "MAKELEVEL",
            "MFLAGS",
            "SX_ROOT",
            "ORCH_PY",
            "PLAN",
            "OUT",
            "BUDGET",
            "RUN",
            "GEN",
            "ARGS",
            "OA_LIB",
            "WORKAREA",
        )
        # `make layout-flow` falls back to `$<PREFIX>_OA_LIB` / `$<PREFIX>_WORKAREA`
        and not k.endswith((layout_lane.OA_LIB_SUFFIX, layout_lane.WORKAREA_SUFFIX))
    }
    if sx_root is not None:
        env["SX_ROOT"] = str(sx_root)
    return subprocess.run(
        ["make", "--no-print-directory", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_make_size_runs_workflows_sizing_on_this_repo(tmp_path):
    root, log = _sx_root(tmp_path)
    r = _make("size", "PLAN=plan.json", "OUT=out/sizing", sx_root=root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert log.read_text().splitlines() == [
        "-m",
        "spicexplorer_orchestration.workflows.sizing",
        ".",
        "plan.json",
        "--out",
        "out/sizing",
    ]


def test_make_size_passes_the_budget_and_the_rest_of_the_arguments(tmp_path):
    root, log = _sx_root(tmp_path)
    r = _make(
        "size",
        "PLAN=plan.json",
        "OUT=o",
        "BUDGET=40",
        "ARGS=--table n=ihp-sg13g2/sg13_lv_nmos --factor 2",
        sx_root=root,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert log.read_text().splitlines()[6:] == [
        "--optimize-budget",
        "40",
        "--table",
        "n=ihp-sg13g2/sg13_lv_nmos",
        "--factor",
        "2",
    ]


@pytest.mark.skipif(
    LANE == "bridge",
    reason="harness.yaml declares lane: bridge; "
    "test_make_layout_flow_on_a_bridge_lane_repo_refuses_without_the_kit_file covers it",
)
def test_make_layout_flow_runs_workflows_layout_on_this_repo(tmp_path):
    root, log = _sx_root(tmp_path)
    r = _make("layout-flow", "RUN=runs/layout", "ARGS=--cell amp", sx_root=root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert log.read_text().splitlines() == [
        "-m",
        "spicexplorer_orchestration.workflows.layout",
        ".",
        "--generator",
        "layout/gen_cell.py",
        "--run-dir",
        "runs/layout",
        "--cell",
        "amp",
    ]


@pytest.mark.skipif(LANE != "bridge", reason="harness.yaml does not declare lane: bridge")
def test_make_layout_flow_on_a_bridge_lane_repo_refuses_without_the_kit_file(tmp_path):
    """On this repo's own `lane: bridge`, with `SX_KIT_FILE` cleared (tests/conftest.py), the
    target refuses before the workflow starts; tests/test_layout_lane.py runs the lane itself on a
    copy with a stand-in kit file."""
    root, log = _sx_root(tmp_path)
    r = _make("layout-flow", "RUN=runs/layout", "OA_LIB=amp_lib", sx_root=root)
    assert r.returncode == 2 and "SX_KIT_FILE" in r.stdout, r.stdout + r.stderr
    assert not log.exists(), "the workflow must not start"


@pytest.mark.parametrize(
    ("target", "args", "says"),
    [
        ("size", ("PLAN=p.json", "OUT=o"), "SX_ROOT is not set"),
        ("layout-flow", ("RUN=r",), "SX_ROOT is not set"),
    ],
)
def test_the_targets_refuse_without_sx_root(target, args, says):
    r = _make(target, *args, sx_root=None)
    assert r.returncode == 2 and says in r.stdout, r.stdout + r.stderr


def test_the_targets_refuse_without_the_orchestration_venv(tmp_path):
    r = _make("size", "PLAN=p.json", "OUT=o", sx_root=tmp_path)
    assert r.returncode == 2 and "no orchestration venv at" in r.stdout, r.stdout + r.stderr


def test_an_explicit_orch_py_needs_no_sx_root(tmp_path):
    root, log = _sx_root(tmp_path)
    py = root / "spicexplorer-orchestration" / ".venv" / "bin" / "python"
    r = _make("size", "PLAN=p.json", "OUT=o", f"ORCH_PY={py}", sx_root=None)
    assert r.returncode == 0, r.stdout + r.stderr
    assert log.read_text().splitlines()[:2] == ["-m", "spicexplorer_orchestration.workflows.sizing"]


@pytest.mark.parametrize(
    ("target", "args", "says"),
    [
        ("size", ("OUT=o",), "make size needs PLAN="),
        ("size", ("PLAN=p.json",), "make size needs PLAN="),
        ("layout-flow", (), "make layout-flow needs RUN="),
    ],
)
def test_the_targets_name_their_missing_argument(tmp_path, target, args, says):
    root, log = _sx_root(tmp_path)
    r = _make(target, *args, sx_root=root)
    assert r.returncode == 2 and says in r.stdout, r.stdout + r.stderr
    assert not log.exists()
