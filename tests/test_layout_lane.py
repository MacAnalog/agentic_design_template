"""The layout lane: `make layout-flow` and `layout/signoff.py` dispatch on `lane:` in harness.yaml.

Hermetic. The commercial lane's platform modules (the kit-file loader, the layout backend, the
batch check engine, the DSPF splice) are replaced in `sys.modules` by stand-ins that record their
calls, so no case needs the platform at the revision that has them, the EDA server or a kit. The
kit is a stand-in object with invented roles; nothing here is a kit fact.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _mod(rel: str, name: str | None = None):
    path = REPO / rel
    name = name or (path.stem + "_lane_test")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # a dataclass in the module looks its module up here
    spec.loader.exec_module(mod)
    return mod


def _needs(rel: str, marker: str = ""):
    """Skip a test whose `layout/` file is not in this repo yet. `make template-update` never
    carries `layout/`, so a design taking v2.15 copies these files by hand before its tests run."""
    path = REPO / rel
    present = path.is_file() and marker in path.read_text()
    what = f"has no {marker!r}" if path.is_file() else "is absent"
    return pytest.mark.skipif(
        not present,
        reason=f"{rel} {what}: bring it across by hand (CHANGELOG.md, v2.15, Taking it, step 2)",
    )


NEEDS_GEN_BRIDGE = _needs("layout/gen_cell_bridge.py")
NEEDS_SIGNOFF_BRIDGE = _needs("layout/signoff.py", "def main_bridge")
NEEDS_PLAN_TEMPLATE = _needs("layout/PLAN.template.md")


layout_lane = _mod("scripts/layout_lane.py")
pdk_links = layout_lane.pdk_links


# --- scripts/layout_lane.py ---------------------------------------------------------------------


def test_the_open_lane_passes_only_the_generator():
    assert layout_lane.lane_args("", env={}) == ["--generator", "layout/gen_cell.py"]
    assert layout_lane.lane_args("ngspice", generator="layout/gen_amp.py", env={}) == [
        "--generator",
        "layout/gen_amp.py",
    ]


def test_the_bridge_lane_passes_the_kit_file_by_name_and_the_oa_library():
    env = {"SX_KIT_FILE": "/somewhere/kit.yaml"}
    assert layout_lane.lane_args("bridge", lib="amp_lib", env=env) == [
        "--generator",
        "layout/gen_cell_bridge.py",
        "--tech",
        "$SX_KIT_FILE",  # the literal: the kit path never reaches a verdict or the ledger
        "--lib",
        "amp_lib",
        "--skip",  # not loaded: the checks would read the OA view, not this build's SKILL
        "drc,lvs,pex,benches",
    ]
    args = layout_lane.lane_args("bridge", lib="amp_lib", workarea="$HOME/wa", env=env)
    assert args[-4:-2] == ["--workarea", "$HOME/wa"]


def test_the_bridge_lane_loads_or_skips_the_checks_never_neither():
    env = {"SX_KIT_FILE": "/somewhere/kit.yaml"}
    loaded = layout_lane.lane_args("bridge", lib="amp_lib", load=True, env=env)
    assert loaded[-1] == "--load" and "--skip" not in loaded
    chose = layout_lane.lane_args("bridge", lib="amp_lib", caller_chose=True, env=env)
    assert "--load" not in chose and "--skip" not in chose  # the caller's ARGS decide
    with pytest.raises(layout_lane.LaneError, match="open lane loads nothing"):
        layout_lane.lane_args("", load=True, env={})


def test_the_bridge_lane_reads_the_prefixed_variables_signoff_reads():
    """An empty `OA_LIB` / `WORKAREA` falls back to `$<PREFIX>_OA_LIB` / `$<PREFIX>_WORKAREA`,
    the variables `layout/signoff.py` reads; the make variable wins over the export."""
    env = {"SX_KIT_FILE": "k.yaml", "AMP_OA_LIB": "amp_lib", "AMP_WORKAREA": "$HOME/wa"}
    args = layout_lane.lane_args("bridge", env=env, prefix="AMP")
    assert args[-6:-2] == ["--lib", "amp_lib", "--workarea", "$HOME/wa"]
    assert (
        layout_lane.lane_args("bridge", lib="other_lib", env=env, prefix="AMP")[-5] == "other_lib"
    )
    with pytest.raises(layout_lane.LaneError, match="AMP_OA_LIB="):
        layout_lane.lane_args("bridge", env={"SX_KIT_FILE": "k.yaml"}, prefix="AMP")
    # the open lane reads neither
    assert layout_lane.lane_args("", env=env, prefix="AMP") == ["--generator", "layout/gen_cell.py"]


@pytest.mark.parametrize(
    ("exp_env", "want"),
    [("exp_env: AMP_EXP", "AMP"), ("exp_env: EXP", "SIM"), ("", "SIM"), ("exp_env: _EXP", "SIM")],
)
def test_env_prefix_is_derived_from_exp_env_as_the_platform_does(tmp_path, exp_env, want):
    (tmp_path / "harness.yaml").write_text(f"name: x\n{exp_env}\n")
    assert layout_lane.env_prefix(tmp_path) == want


@pytest.mark.parametrize(
    ("lane", "kw", "env", "says"),
    [
        ("bridge", {"lib": "amp_lib"}, {}, "SX_KIT_FILE"),
        ("bridge", {"lib": "amp_lib"}, {"SX_KIT_FILE": "  "}, "SX_KIT_FILE"),
        ("bridge", {}, {"SX_KIT_FILE": "k.yaml"}, "OA_LIB="),
        ("magic", {}, {}, "lane: magic"),
        ("", {"generator": "layout/my gen.py"}, {}, "white space"),
    ],
)
def test_a_lane_that_cannot_run_is_refused_with_its_fix(lane, kw, env, says):
    with pytest.raises(layout_lane.LaneError, match=says):
        layout_lane.lane_args(lane, env=env, **kw)


def test_declared_lane_reads_the_top_level_key(tmp_path):
    (tmp_path / "harness.yaml").write_text("name: x\nopts:\n  lane: bridge\n")
    assert layout_lane.declared_lane(tmp_path) == ""
    (tmp_path / "harness.yaml").write_text("name: x\nlane: bridge   # the commercial kit\n")
    assert layout_lane.declared_lane(tmp_path) == "bridge"
    assert layout_lane.declared_lane(tmp_path / "missing") == ""


# --- make layout-flow on a bridge-lane copy of the template -------------------------------------


def _bridge_copy(tmp_path: Path) -> Path:
    """The Makefile, the two scripts it runs and a harness.yaml that declares `lane: bridge`."""
    root = tmp_path / "design"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "Makefile", root / "Makefile")
    for name in ("layout_lane.py", "pdk_links.py"):
        shutil.copy(REPO / "scripts" / name, root / "scripts" / name)
    text = (REPO / "harness.yaml").read_text() + "\nlane: bridge\n"
    (root / "harness.yaml").write_text(text)
    return root


def _orch_stub(tmp_path: Path) -> tuple[Path, Path]:
    py = tmp_path / "ws" / "spicexplorer-orchestration" / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    log = tmp_path / "argv"
    py.write_text(f'#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done > "{log}"\nexit 0\n')
    py.chmod(0o755)
    return tmp_path / "ws", log


def _make(
    root: Path, sx_root: Path, *args: str, kit: str | None, extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    drop = (
        "MAKEFLAGS",
        "MAKELEVEL",
        "MFLAGS",
        "ORCH_PY",
        "GEN",
        "OA_LIB",
        "WORKAREA",
        "ARGS",
        "LOAD",
    )
    suffixes = (layout_lane.OA_LIB_SUFFIX, layout_lane.WORKAREA_SUFFIX)
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in (*drop, "SX_KIT_FILE") and not k.endswith(suffixes)
    }
    env["SX_ROOT"] = str(sx_root)
    env["PY"] = sys.executable
    if kit is not None:
        env["SX_KIT_FILE"] = kit
    env.update(extra or {})
    return subprocess.run(
        ["make", "--no-print-directory", "layout-flow", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_make_layout_flow_on_the_bridge_lane_runs_the_kit_lane(tmp_path):
    root = _bridge_copy(tmp_path)
    ws, log = _orch_stub(tmp_path)
    r = _make(root, ws, "RUN=runs/l", "OA_LIB=amp_lib", "ARGS=--cell amp", kit="/k/kit.yaml")
    assert r.returncode == 0, r.stdout + r.stderr
    assert log.read_text().splitlines() == [
        "-m",
        "spicexplorer_orchestration.workflows.layout",
        ".",
        "--generator",
        "layout/gen_cell_bridge.py",
        "--tech",
        "$SX_KIT_FILE",
        "--lib",
        "amp_lib",
        "--skip",
        "drc,lvs,pex,benches",
        "--run-dir",
        "runs/l",
        "--cell",
        "amp",
    ]
    assert "DRC, LVS, PEX and the benches were skipped" in r.stderr


def test_make_layout_flow_load_1_loads_the_skill_and_runs_the_checks(tmp_path):
    root = _bridge_copy(tmp_path)
    ws, log = _orch_stub(tmp_path)
    r = _make(root, ws, "RUN=r", "OA_LIB=amp_lib", "LOAD=1", kit="/k/kit.yaml")
    assert r.returncode == 0, r.stdout + r.stderr
    argv = log.read_text().splitlines()
    assert "--load" in argv and "--skip" not in argv
    assert "skipped" not in r.stderr


@pytest.mark.parametrize("args", ["--skip build --cell amp", "--load"])
def test_make_layout_flow_leaves_the_stages_to_args_that_choose_them(tmp_path, args):
    root = _bridge_copy(tmp_path)
    ws, log = _orch_stub(tmp_path)
    r = _make(root, ws, "RUN=r", "OA_LIB=amp_lib", f"ARGS={args}", kit="/k/kit.yaml")
    assert r.returncode == 0, r.stdout + r.stderr
    argv = log.read_text().splitlines()
    assert "drc,lvs,pex,benches" not in argv and argv[-len(args.split()) :] == args.split()
    assert "skipped" not in r.stderr


def test_make_layout_flow_takes_load_from_the_command_line_only(tmp_path):
    root = _bridge_copy(tmp_path)  # loading replaces the layout view: an exported LOAD is ignored
    ws, log = _orch_stub(tmp_path)
    r = _make(root, ws, "RUN=r", "OA_LIB=amp_lib", kit="/k/kit.yaml", extra={"LOAD": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    argv = log.read_text().splitlines()
    assert "--load" not in argv and "drc,lvs,pex,benches" in argv


def test_make_layout_flow_refuses_load_on_the_open_lane(tmp_path):
    root = _bridge_copy(tmp_path)
    harness = root / "harness.yaml"
    harness.write_text(harness.read_text().replace("\nlane: bridge\n", "\n"))
    ws, log = _orch_stub(tmp_path)
    r = _make(root, ws, "RUN=r", "LOAD=1", kit=None)
    assert r.returncode == 2 and "open lane loads nothing" in r.stdout, r.stdout + r.stderr
    assert not log.exists()


def test_make_layout_flow_passes_a_remote_home_workarea_unexpanded(tmp_path):
    root = _bridge_copy(tmp_path)
    ws, log = _orch_stub(tmp_path)
    r = _make(root, ws, "RUN=r", "OA_LIB=amp_lib", "WORKAREA=$$HOME/wa", kit="/k/kit.yaml")
    assert r.returncode == 0, r.stdout + r.stderr
    argv = log.read_text().splitlines()
    assert argv[argv.index("--workarea") + 1] == "$HOME/wa"


def test_make_layout_flow_takes_the_oa_library_from_the_prefixed_variable(tmp_path):
    root = _bridge_copy(tmp_path)  # exp_env: EXP, so the prefix is SIM
    ws, log = _orch_stub(tmp_path)
    r = _make(root, ws, "RUN=r", kit="/k/kit.yaml", extra={"SIM_OA_LIB": "amp_lib"})
    assert r.returncode == 0, r.stdout + r.stderr
    argv = log.read_text().splitlines()
    assert argv[argv.index("--lib") + 1] == "amp_lib"


@pytest.mark.parametrize(
    ("args", "kit", "says"),
    [
        (("RUN=r", "OA_LIB=amp_lib"), None, "SX_KIT_FILE"),
        (("RUN=r",), "/k/kit.yaml", "OA_LIB="),
    ],
)
def test_make_layout_flow_refuses_a_bridge_lane_it_cannot_run(tmp_path, args, kit, says):
    root = _bridge_copy(tmp_path)
    ws, log = _orch_stub(tmp_path)
    r = _make(root, ws, *args, kit=kit)
    assert r.returncode == 2 and says in r.stdout, r.stdout + r.stderr
    assert not log.exists(), "the workflow must not start"


# --- layout/gen_cell_bridge.py ------------------------------------------------------------------

gen = _mod("layout/gen_cell_bridge.py") if (REPO / "layout/gen_cell_bridge.py").is_file() else None


@NEEDS_GEN_BRIDGE
def test_every_knob_has_a_bound_and_its_default_is_inside_it():
    import dataclasses

    names = {f.name for f in dataclasses.fields(gen.LayoutParams)}
    assert names == set(gen.BOUNDS)
    gen.layout_params({})  # the defaults pass their own bounds


@NEEDS_GEN_BRIDGE
def test_layout_params_refuses_unknown_and_out_of_bounds_knobs():
    assert gen.layout_params({"dev_gap": 2, "sizing": "s.json"}).dev_gap == 2.0
    with pytest.raises(ValueError, match="unknown layout knob"):
        gen.layout_params({"dev_gapp": 2})
    with pytest.raises(ValueError, match="outside BOUNDS"):
        gen.layout_params({"dev_gap": 99})


class _FakeKit:
    """Roles only; `device` raises KeyError for an unknown role, as the kit loader does."""

    def __init__(self, roles):
        self.roles = roles

    def device(self, role):
        if role not in self.roles:
            raise KeyError(f"kit has no device role {role!r}")
        return types.SimpleNamespace(role=role)


@pytest.fixture
def fake_backend(monkeypatch):
    """`spicexplorer_layout.backends.<editor>` with the two names the template uses."""
    seen: dict[str, object] = {}

    @dataclass
    class LayoutPlan:
        cell: str
        instances: list = field(default_factory=list)

    def write_skill(plan, kit, path, *, lib):
        seen["write_skill"] = {"cell": plan.cell, "lib": lib, "path": Path(path)}
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("; skill\n")
        return Path(path)

    def load_layout(il, *, client=None):
        seen["load_layout"] = Path(il)
        return types.SimpleNamespace(ok=True, error="")

    pkg = types.ModuleType("spicexplorer_layout")
    backends = types.ModuleType("spicexplorer_layout.backends")
    editor = types.ModuleType("spicexplorer_layout.backends.virtuoso")
    editor.LayoutPlan, editor.write_skill, editor.load_layout = LayoutPlan, write_skill, load_layout
    for name, mod in (
        ("spicexplorer_layout", pkg),
        ("spicexplorer_layout.backends", backends),
        ("spicexplorer_layout.backends.virtuoso", editor),
    ):
        monkeypatch.setitem(sys.modules, name, mod)
    seen["LayoutPlan"] = LayoutPlan
    return seen


@NEEDS_GEN_BRIDGE
def test_the_skeleton_resolves_its_roles_then_asks_to_be_drawn(fake_backend, tmp_path):
    sizing = tmp_path / "sizing.json"
    sizing.write_text(json.dumps({"m1": {"w": 1}}))
    with pytest.raises(NotImplementedError, match="draw <cell>"):
        gen.plan({"sizing": str(sizing)}, _FakeKit({"nmos", "pmos"}))
    with pytest.raises(KeyError, match="pmos"):
        gen.plan({}, _FakeKit({"nmos"}))


# --- layout/signoff.py on the bridge lane -------------------------------------------------------


@dataclass
class _Result:
    passed: bool = True
    available: bool = True
    matched: bool = True
    ok: bool = True
    n_violations: int = 0
    n_density_violations: int = 3
    violations: list = field(default_factory=list)
    n_c: int = 4
    n_r: int = 2
    per_net_c_ff: dict = field(default_factory=lambda: {"out": 1.5})
    port_order: list = field(default_factory=list)
    netlist_path: str = ""
    log: str = ""
    reason: str = ""

    def to_dict(self):
        from dataclasses import asdict

        return asdict(self)


@pytest.fixture
def fake_kit_lane(fake_backend, monkeypatch, tmp_path):
    """The kit loader, the batch check engine and the DSPF splice, each recording its call."""
    seen = fake_backend
    dspf = tmp_path / "amp.pex.netlist"
    dspf.write_text("* dspf\n")

    # only the submodule: the real `spicexplorer_core` stays, the design's lane imports it
    kitmod = types.ModuleType("spicexplorer_core.kit")
    kitmod.KIT_FILE_ENV = "SX_KIT_FILE"
    kitmod.load_kit = lambda: types.SimpleNamespace(info=types.SimpleNamespace(name="fakekit"))

    @dataclass
    class CalibreJob:
        cell: str
        lib: str | None = None
        checks: tuple = ()
        workarea: str | None = None

    def run_calibre(kit, job, *, work_root, runner=None):
        seen.setdefault("run_calibre", []).append({"job": job, "work_root": work_root})
        return types.SimpleNamespace(
            dir=work_root / "run",
            status="ok",
            reason="",
            drc=_Result() if "drc" in job.checks else None,
            lvs=_Result() if "lvs" in job.checks else None,
            pex=_Result(port_order=["OUT", "INP"], netlist_path=str(dspf))
            if "pex" in job.checks
            else None,
        )

    so = types.ModuleType("spicexplorer_signoff")
    cal = types.ModuleType("spicexplorer_signoff.calibre")
    cal.CalibreJob, cal.run_calibre = CalibreJob, run_calibre

    def splice_dspf(deck, path, port_order, *, cell, drop_includes=(), include_as=None):
        seen.setdefault("splice", []).append(
            {"cell": cell, "ports": list(port_order), "drop": list(drop_includes), "as": include_as}
        )
        return types.SimpleNamespace(deck=deck + f"dspf_include {include_as}\n", instances=(1,))

    sp = types.ModuleType("spicexplorer_spectre")
    post = types.ModuleType("spicexplorer_spectre.postlayout")
    post.splice_dspf = splice_dspf
    for name, mod in (
        ("spicexplorer_core.kit", kitmod),
        ("spicexplorer_signoff", so),
        ("spicexplorer_signoff.calibre", cal),
        ("spicexplorer_spectre", sp),
        ("spicexplorer_spectre.postlayout", post),
    ):
        monkeypatch.setitem(sys.modules, name, mod)
    seen["dspf"] = dspf
    return seen


def _signoff(monkeypatch, tmp_path, *, cell="amp"):
    """layout/signoff.py on the bridge lane, with a generator that returns a plan for `cell`."""
    so = _mod("layout/signoff.py", "signoff_bridge_lane_test")
    gen_file = tmp_path / "gen_amp_bridge.py"
    gen_file.write_text(
        "import sys\n"
        "def plan(params, kit):\n"
        "    LayoutPlan = sys.modules['spicexplorer_layout.backends.virtuoso'].LayoutPlan\n"
        f"    return LayoutPlan({cell!r}, instances=[1, 2])\n"
    )
    monkeypatch.setattr(so, "LANE", "bridge")
    monkeypatch.setattr(so, "CELL", "amp")
    monkeypatch.setattr(so, "GEN_BRIDGE", gen_file)
    reference = types.SimpleNamespace(benches=lambda: ["ac", "op"], deck=lambda b: f"* {b}\n")
    monkeypatch.setattr(so, "REFERENCE", reference)
    return so


@NEEDS_SIGNOFF_BRIDGE
def test_the_bridge_lane_refuses_without_the_kit_file(fake_kit_lane, monkeypatch, tmp_path):
    so = _signoff(monkeypatch, tmp_path)
    monkeypatch.delenv("SX_KIT_FILE", raising=False)
    with pytest.raises(SystemExit, match="SX_KIT_FILE"):
        so.kit()


@NEEDS_SIGNOFF_BRIDGE
def test_the_bridge_lane_refuses_without_an_oa_library(monkeypatch, tmp_path):
    so = _signoff(monkeypatch, tmp_path)
    monkeypatch.delenv(so.OA_LIB_ENV, raising=False)
    with pytest.raises(SystemExit, match=so.OA_LIB_ENV):
        so.oa_lib(None)
    monkeypatch.setenv(so.OA_LIB_ENV, "amp_lib")
    assert so.oa_lib(None) == "amp_lib" and so.oa_lib("other_lib") == "other_lib"


@NEEDS_SIGNOFF_BRIDGE
def test_main_on_the_bridge_lane_runs_every_stage_through_one_check_run(
    fake_kit_lane, monkeypatch, tmp_path
):
    so = _signoff(monkeypatch, tmp_path)
    monkeypatch.setenv("SX_KIT_FILE", "/k/kit.yaml")
    runs: list[dict] = []

    def run_decks(decks, tag, *, record=True, run_kwargs=None):
        runs.append({"tag": tag, "run_kwargs": run_kwargs, "decks": dict(decks)})
        return {"gain_db": 60.0}, {b: {"status": "ok"} for b in decks}

    monkeypatch.setattr(so.M, "run_decks", run_decks)
    monkeypatch.setattr(so.M, "table", lambda cols: "| table |")
    out = tmp_path / "out"
    assert so.main(["--all", "--load", "--out", str(out), "--lib", "amp_lib"]) == 0

    rec = json.loads((out / "signoff.json").read_text())
    assert rec["lane"] == "bridge"
    assert fake_kit_lane["write_skill"]["lib"] == "amp_lib"
    assert rec["build"]["instances"] == 2 and rec["build"]["loaded"] is True
    assert fake_kit_lane["load_layout"] == Path(rec["build"]["skill"])
    calls = fake_kit_lane["run_calibre"]
    assert len(calls) == 1 and calls[0]["job"].checks == ("drc", "lvs", "pex")
    assert calls[0]["job"].lib == "amp_lib" and calls[0]["job"].cell == "amp"
    assert rec["drc"]["passed"] is True and rec["drc"]["n_density_violations"] == 3
    assert rec["lvs"]["matched"] is True
    assert rec["pex"]["port_order"] == ["OUT", "INP"]
    assert rec["current_density"]["skipped"] is True
    # the post-layout row: spliced decks, the DSPF staged beside each, the same run_decks
    assert [r["tag"] for r in runs] == ["postlayout_pre", "postlayout_post"]
    assert runs[0]["run_kwargs"] is None
    staged = runs[1]["run_kwargs"]["extra_files"]
    (name,) = staged
    assert staged[name] == fake_kit_lane["dspf"].read_text()
    assert all(s["ports"] == ["OUT", "INP"] and s["cell"] == "amp" for s in fake_kit_lane["splice"])
    assert all(s["as"] == name for s in fake_kit_lane["splice"])
    assert all(d.endswith(f"dspf_include {name}\n") for d in runs[1]["decks"].values())

    assert (out / "scorecard.md").read_text() == "| table |\n"


@NEEDS_SIGNOFF_BRIDGE
@pytest.mark.parametrize(
    "stages", [["--all"], ["--stages", "build,drc"], ["--stages", "build,pex"]]
)
def test_build_with_checks_but_no_load_is_refused_before_any_stage(
    fake_kit_lane, monkeypatch, tmp_path, stages
):
    """DRC/LVS/PEX read the layout view in the library, not the SKILL this build writes:
    the same rule `workflows.layout` applies, so both entry points agree."""
    so = _signoff(monkeypatch, tmp_path)
    monkeypatch.setenv("SX_KIT_FILE", "/k/kit.yaml")
    with pytest.raises(SystemExit, match="--load"):
        so.main([*stages, "--out", str(tmp_path / "o"), "--lib", "amp_lib"])
    assert "write_skill" not in fake_kit_lane and "run_calibre" not in fake_kit_lane


@NEEDS_SIGNOFF_BRIDGE
@pytest.mark.parametrize("stages", ["build", "build,jmax", "drc,lvs,pex"])
def test_build_alone_or_checks_alone_run_without_load(fake_kit_lane, monkeypatch, tmp_path, stages):
    so = _signoff(monkeypatch, tmp_path)
    monkeypatch.setenv("SX_KIT_FILE", "/k/kit.yaml")
    assert so.main(["--stages", stages, "--out", str(tmp_path / "o"), "--lib", "amp_lib"]) == 0


@NEEDS_SIGNOFF_BRIDGE
def test_the_staged_dspf_is_named_for_its_content(fake_kit_lane, monkeypatch, tmp_path):
    """The lane keys a run on the deck text: a re-extracted DSPF must change the deck."""
    so = _signoff(monkeypatch, tmp_path)
    names: list[str] = []

    def run_decks(decks, tag, *, record=True, run_kwargs=None):
        if run_kwargs:
            names.extend(run_kwargs["extra_files"])
        return {}, {b: {"status": "ok"} for b in decks}

    monkeypatch.setattr(so.M, "run_decks", run_decks)
    monkeypatch.setattr(so.M, "table", lambda cols: "")
    dspf = fake_kit_lane["dspf"]
    so.benches_bridge(dspf, ["OUT"], tmp_path)
    dspf.write_text("* re-extracted\n")
    so.benches_bridge(dspf, ["OUT"], tmp_path)
    assert len(set(names)) == 2 and all(n.startswith("amp.") for n in names)


@NEEDS_SIGNOFF_BRIDGE
def test_benches_reuse_the_dspf_of_an_earlier_run(fake_kit_lane, monkeypatch, tmp_path):
    so = _signoff(monkeypatch, tmp_path)
    monkeypatch.setenv("SX_KIT_FILE", "/k/kit.yaml")
    monkeypatch.setattr(
        so.M, "run_decks", lambda d, t, **kw: ({}, {b: {"status": "ok"} for b in d})
    )
    monkeypatch.setattr(so.M, "table", lambda cols: "")
    out = tmp_path / "out"
    assert so.main(["--stages", "pex", "--out", str(out), "--lib", "amp_lib"]) == 0
    assert so.main(["--stages", "benches", "--out", str(out), "--lib", "amp_lib"]) == 0
    assert len(fake_kit_lane["run_calibre"]) == 1  # benches started no second check run
    assert "benches" in json.loads((out / "signoff.json").read_text())


@NEEDS_SIGNOFF_BRIDGE
def test_benches_without_a_dspf_say_to_run_pex_first(fake_kit_lane, monkeypatch, tmp_path):
    so = _signoff(monkeypatch, tmp_path)
    monkeypatch.setenv("SX_KIT_FILE", "/k/kit.yaml")
    with pytest.raises(SystemExit, match="run the pex stage first"):
        so.main(["--stages", "benches", "--out", str(tmp_path / "o"), "--lib", "amp_lib"])


@NEEDS_SIGNOFF_BRIDGE
def test_a_stage_of_the_other_lane_is_refused(fake_kit_lane, monkeypatch, tmp_path):
    so = _signoff(monkeypatch, tmp_path)
    with pytest.raises(SystemExit, match="render"):
        so.main(["--stages", "render", "--out", str(tmp_path / "o"), "--lib", "amp_lib"])


@NEEDS_SIGNOFF_BRIDGE
def test_a_generator_that_builds_another_cell_is_refused(fake_kit_lane, monkeypatch, tmp_path):
    so = _signoff(monkeypatch, tmp_path, cell="not_amp")
    monkeypatch.setenv("SX_KIT_FILE", "/k/kit.yaml")
    with pytest.raises(SystemExit, match="not_amp"):
        so.build_bridge(tmp_path / "o", "amp_lib")


@NEEDS_SIGNOFF_BRIDGE
def test_load_hands_the_skill_file_to_the_editor(fake_kit_lane, monkeypatch, tmp_path):
    so = _signoff(monkeypatch, tmp_path)
    monkeypatch.setenv("SX_KIT_FILE", "/k/kit.yaml")
    rec = so.build_bridge(tmp_path / "o", "amp_lib", load=True)
    assert rec["loaded"] is True
    assert fake_kit_lane["load_layout"] == Path(rec["skill"])


# --- design.metrics.run_decks forwards the lane's options ---------------------------------------


def test_run_decks_passes_run_kwargs_to_every_sim_run(monkeypatch):
    # through `package:`, never spelled `design.`: `make template-update` re-roots this file's
    # PATH onto a renamed package but never rewrites its text (scripts/template_update.py)
    package = pdk_links.declared((REPO / "harness.yaml").read_text(), "package") or "design"
    metrics = importlib.import_module(f"{package}.metrics")

    seen: list[dict] = []

    class _R:
        measures, failed, wall = {}, [], 0.1

    def run(deck, tag, **kw):
        seen.append(kw)
        return _R()

    monkeypatch.setattr(metrics.sim, "run", run)
    monkeypatch.setattr(metrics, "log_run", lambda *a, **k: None)
    metrics.run_decks({"a": "* a\n", "b": "* b\n"}, "t", run_kwargs={"extra_files": {"x": "y"}})
    assert seen == [{"extra_files": {"x": "y"}}] * 2
    seen.clear()
    metrics.run_decks({"a": "* a\n"}, "t")
    assert seen == [{}]


# --- the lane-aware denylist (scripts/lint.py) --------------------------------------------------

lint = _mod("scripts/lint.py")


def _harness(tmp_path: Path, lane: str, entries: str):
    from spicexplorer_harness import load

    text = f"name: x\npackage: design\n{'lane: ' + lane if lane else ''}\ndenylist:\n{entries}"
    (tmp_path / "harness.yaml").write_text(text)
    return load(tmp_path)


_ENTRIES = (
    '  - {pattern: "\\\\bzorblat\\\\b", why: made-up word, exempt_lanes: [bridge]}\n'
    '  - {pattern: "\\\\bquuxite\\\\b", why: made-up word}\n'
)


def test_the_bridge_lane_drops_only_the_entries_marked_for_it(tmp_path):
    h = lint.lane_denylist(_harness(tmp_path, "bridge", _ENTRIES))
    assert [d["why"] for d in h.denylist] == ["made-up word"]
    assert "quuxite" in h.denylist[0]["pattern"]


def test_the_open_lane_keeps_every_entry(tmp_path):
    h = _harness(tmp_path, "", _ENTRIES)
    assert lint.lane_denylist(h) is h and len(h.denylist) == 2


def test_an_exempt_lanes_that_is_not_a_list_is_a_failure(tmp_path):
    from spicexplorer_harness.lint import Lint

    h = _harness(tmp_path, "bridge", '  - {pattern: "a", why: w, exempt_lanes: bridge}\n')
    h = lint.lane_denylist(h)
    assert len(h.denylist) == 1, "a malformed exemption exempts nothing"
    L = Lint(h)
    lint.denylist_lanes(L)
    assert len(L.fails) == 1 and "exempt_lanes" in L.fails[0]


def test_the_template_denylist_lifts_the_simulator_and_editor_names_on_the_bridge_lane():
    """The template's own entries: on `lane: bridge` the vendor simulator and the kit's editor
    are allowed, the rest stay banned; a dotted module path never matched the editor pattern."""
    import dataclasses
    import re

    from spicexplorer_harness import load

    h = load(REPO)
    bridged = lint.lane_denylist(dataclasses.replace(h, lane="bridge"))
    kept = {d["why"] for d in bridged.denylist}
    lifted = [d for d in h.denylist if d["why"] not in kept]
    exempt = [
        d
        for d in h.denylist
        if isinstance(d.get("exempt_lanes"), list) and "bridge" in d["exempt_lanes"]
    ]
    # holds in a design that adds its own bridge-exempt entries
    assert lifted and lifted == exempt
    # this file is itself scanned by the denylist, so the word is read from the pattern
    src = next(d["pattern"] for d in lifted if "editor" in d["why"])
    editor = re.search(r"\\b(\w+)\\b", src).group(1)
    rx = re.compile(src, re.IGNORECASE)
    assert rx.search(f"the {editor} session")
    assert not rx.search("from spicexplorer_layout.backends." + editor + " import LayoutPlan")


def test_make_lint_applies_the_exemption_through_main(tmp_path, capsys, monkeypatch):
    """`scripts/lint.py main` is what `make lint` runs: the filtered list must reach the harness's
    own `denylist` check, on the bridge lane only. Made-up words; the fixture fails other checks,
    so only the denylist report is compared."""
    monkeypatch.setattr(lint, "EXTRA", ())
    root = tmp_path / "fixture"
    (root / "doc").mkdir(parents=True)
    (root / "doc" / "notes.md").write_text("the zorblat lane and the quuxite tool\n")
    base = "name: fixture\npackage: design\nexp_env: EXP\njobs_env: JOBS\n"
    reports = {}
    for lane in ("", "bridge"):
        text = base + (f"lane: {lane}\n" if lane else "") + "denylist:\n" + _ENTRIES
        (root / "harness.yaml").write_text(text)
        lint.main(root)
        out = capsys.readouterr().out
        reports[lane] = {w for w in ("zorblat", "quuxite") if f"'{w}'" in out}
    assert reports[""] == {"zorblat", "quuxite"}
    assert reports["bridge"] == {"quuxite"}


# --- layout/PLAN.template.md --------------------------------------------------------------------

PLAN_TEMPLATE = REPO / "layout" / "PLAN.template.md"
#: each section heading the plan must carry, and a column its table must have
PLAN_SECTIONS = {
    "Research inputs": "`LAYOUT-RESEARCH.md` section",
    "Outline and aspect": "aspect ratio ceiling",
    "Device groups and matching patterns": "tolerated mismatch",
    "Dummies": "dummies per row end",
    "Guard rings and taps": "well island",
    "Pin frame": "side",
    "Per-net metal stack": "via count per transition",
    "Generator knobs": "range",
    "Assumed approvals": "",
    "Plan review": "PLAN-REVIEW.md",
    "Plan revisions": "feedback that drove it",
}
#: the *Plan revisions* columns of the library's `layout-designer` definition, in its order
PLAN_REVISION_COLUMNS = [
    "version",
    "round",
    "decision (section, from -> to)",
    "feedback that drove it",
    "evidence path",
]


def _plan_sections() -> dict[str, str]:
    """Each `## N. <title>` heading of the plan skeleton, mapped to the text under it."""
    out: dict[str, str] = {}
    title = None
    for line in PLAN_TEMPLATE.read_text().splitlines():
        if line.startswith("## "):
            title = line[3:].split(". ", 1)[-1].strip()
            out[title] = ""
        elif title is not None:
            out[title] += line + "\n"
    return out


@NEEDS_PLAN_TEMPLATE
@pytest.mark.parametrize("section", sorted(PLAN_SECTIONS))
def test_plan_template_carries_each_decision_section(section: str) -> None:
    sections = _plan_sections()
    assert section in sections, f"layout/PLAN.template.md has no section {section!r}"
    assert PLAN_SECTIONS[section] in sections[section]


@NEEDS_PLAN_TEMPLATE
def test_plan_template_metal_stack_rows_name_their_reason() -> None:
    header = next(
        line
        for line in _plan_sections()["Per-net metal stack"].splitlines()
        if line.startswith("| ")
    )
    assert "because" in header, "Per-net metal stack: no reason column"


@NEEDS_PLAN_TEMPLATE
def test_plan_template_carries_a_plan_version_under_its_title() -> None:
    lines = [line for line in PLAN_TEMPLATE.read_text().splitlines() if line.strip()]
    assert lines[0].startswith("# ") and lines[1] == "plan-version: 1", lines[:2]


@NEEDS_PLAN_TEMPLATE
def test_plan_revisions_table_has_the_layout_designer_columns() -> None:
    raw = _plan_sections()["Plan revisions"]
    header = next(line for line in raw.splitlines() if line.startswith("| "))
    text = " ".join(raw.split())
    assert [c.strip() for c in header.strip("|").split("|")] == PLAN_REVISION_COLUMNS
    assert "geometry only" in text, "an unchanged decision needs its `geometry only` row"
    assert "review round" in text, "a review round is a revisit trigger"


@NEEDS_PLAN_TEMPLATE
def test_plan_review_states_the_loop_bound() -> None:
    text = " ".join(_plan_sections()["Plan review"].split())
    assert "second plan review still has open findings" in text and "hands back" in text
    assert "at most 4" in text, "the geometry review rounds are bounded"
    assert "PLAN-REVIEW-1.md" in text, "the first plan review is kept under its own name"
    claude = " ".join((REPO / "CLAUDE.md").read_text().split())
    assert "second plan review still has open findings" in claude and "at most 4" in claude
    assert "PLAN-REVIEW-1.md" in claude


@NEEDS_PLAN_TEMPLATE
def test_plan_decisions_may_rest_on_a_research_section() -> None:
    """`layout-brief-author` writes `LAYOUT-RESEARCH.md` beside `BRIEF.md`; the definition takes a
    decision's reason from either, so the reason line admits both."""
    text = " ".join(PLAN_TEMPLATE.read_text().split())
    reason = text[text.index("**Every decision names its reason**") :][:200]
    assert "`BRIEF.md` row" in reason and "`LAYOUT-RESEARCH.md` section" in reason
