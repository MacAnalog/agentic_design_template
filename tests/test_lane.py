"""Lane selection, and the bridge lane's pure parts.

Two halves, and the second one is the reason this file exists rather than living in
`test_design.py`:

* **selection** — `design/sim.py` reads `lane:` and re-exports one module. Absent must be the open
  lane, an unknown value must be refused by name.
* **the bridge lane** — `design/sim_bridge.py` + `design/pdk.py` against a RECORDING STUB of the
  platform's bridge-lane package. The template's venv does not install that package (a
  commercial-PDK design adds it — `pyproject.toml`), and nothing in a test may reach the lab's EDA
  server, so what is pinned here is the WRAPPER: the work root, the mode args, token restoration,
  the revision pin, and every message. The remote half — upload, run, download, result parsing — is
  the platform's and is tested there; **no test in this file has ever seen a real bridge.**
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from design import sim

# ------------------------------------------------------------------ selection ---------

def test_the_shipped_lane_is_the_open_one_and_sim_IS_that_module():
    assert sim.LANE == "ngspice", "the template ships with `lane:` absent"
    assert sim.__name__ == "design.sim_ngspice"
    assert sys.modules["design.sim"] is sys.modules["design.sim_ngspice"]
    # the swap, not a star-import: assigning a lane constant through `design.sim` must be the same
    # object the lane's own functions read, which is what makes `monkeypatch.setattr(sim, ...)` work
    assert sim.resolve.__module__ == "design.sim_ngspice"


def test_lane_absent_or_blank_is_the_open_lane():
    assert sim.module_name("") == "sim_ngspice"
    assert sim.module_name("   ") == "sim_ngspice"
    assert sim.module_name("ngspice") == "sim_ngspice"
    assert sim.DEFAULT_LANE == "ngspice"


def test_the_bridge_lane_names_its_module():
    assert sim.module_name("bridge") == "sim_bridge"
    assert set(sim.LANES) == {"ngspice", "bridge"}


def test_the_key_is_read_through_getattr_so_an_older_platform_still_loads(monkeypatch):
    """`lane:` reaches the dispatcher as `getattr(H, "lane", "")`.

    A platform whose `Harness` has no such field therefore does not break the open lane — it
    refuses the KEY itself, in `load()`, which is the loud failure and not a silent default.
    """
    ns = sim.lane_name.__globals__          # the dispatcher's namespace, alive behind the swap
    monkeypatch.setitem(ns, "load", lambda root: types.SimpleNamespace(lane="bridge"))
    assert sim.lane_name() == "bridge"
    monkeypatch.setitem(ns, "load", lambda root: types.SimpleNamespace())
    assert sim.lane_name() == "ngspice", "a platform without the field is the default lane"
    monkeypatch.setitem(ns, "load", lambda root: types.SimpleNamespace(lane="  "))
    assert sim.lane_name() == "ngspice"


def test_an_unknown_lane_is_refused_and_names_the_ones_that_ship():
    with pytest.raises(ValueError) as e:
        sim.module_name("remote")
    msg = str(e.value)
    assert "remote" in msg and "bridge" in msg and "ngspice" in msg


# ------------------------------------------------------------------ the stub ----------

class _Run:
    """What the platform lane returns; only the fields this wrapper touches."""

    def __init__(self, deck: str):
        self.deck, self.raws, self.measures, self.failed, self.wall = deck, ["psf"], {}, [], 0.1


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    """`design.sim_bridge` + `design.pdk` over a recording stub of the platform's lane package."""
    calls: dict[str, dict] = {}

    def run_deck(deck, label, **kw):
        calls["run_deck"] = {"deck": deck, "label": label, **kw}
        return _Run(deck)

    def work_root(name, **kw):
        calls["work_root"] = {"name": name, **kw}
        return tmp_path / "work"

    def preflight(**kw):
        calls["preflight"] = kw
        return {"ok": True, "note": "stubbed", "scalars": ["dc_v1:i"], "psf": ["psf"]}

    class SimError(RuntimeError):
        pass

    class LaneNotConfigured(SimError):
        pass

    lane = types.ModuleType("spicexplorer_spectre.lane")
    lane.DECK_NAME = "input.scs"
    lane.SimError, lane.LaneNotConfigured, lane.Run = SimError, LaneNotConfigured, _Run
    lane.run_deck, lane.work_root = run_deck, work_root
    lane.mode_args = lambda mode: [f"+{mode}"]
    lane.slug = lambda s: "".join(c if c.isalnum() else "_" for c in s).strip("_")
    lane.deck_hash = lambda d: "hash"
    lane.redact = lambda t: t
    lane.tail = lambda t, n=25: t
    lane.host = lambda: "here"

    results = types.ModuleType("spicexplorer_spectre.results")
    results.psf = results.psf_dir = results.psf_dirs = results.scalars = lambda *a, **k: None
    results.wall_time = lambda *a, **k: 0.0

    doctor = types.ModuleType("spicexplorer_spectre.doctor")
    doctor.PROBE, doctor.PROBE_KEYS, doctor.preflight = "// one resistor\n", ("dc_v1:i",), preflight

    pkg = types.ModuleType("spicexplorer_spectre")
    pkg.lane, pkg.results, pkg.doctor = lane, results, doctor
    for name, mod in (("spicexplorer_spectre", pkg), ("spicexplorer_spectre.lane", lane),
                      ("spicexplorer_spectre.results", results),
                      ("spicexplorer_spectre.doctor", doctor)):
        monkeypatch.setitem(sys.modules, name, mod)
    for name in ("design.sim_bridge", "design.pdk"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    import importlib

    sim_bridge = importlib.import_module("design.sim_bridge")
    pdk = importlib.import_module("design.pdk")
    monkeypatch.setattr(pdk, "REVISION", "proc_rev_v1d0")
    monkeypatch.setattr(pdk, "SECTIONS", {"core": "tt", "stat": "mis"})
    monkeypatch.setattr(pdk, "LIB_ENV", "PFX_PDK_LIB")
    monkeypatch.setattr(pdk, "LIB_ENV_SCOPED", "XY001_PDK_LIB")
    monkeypatch.setattr(pdk, "TOKEN", "$PFX_PDK_LIB")
    for n in ("XY001_PDK_LIB", "PFX_PDK_LIB", "XY001_PDK_LIB_ALLOW_MISMATCH",
              "PFX_PDK_LIB_ALLOW_MISMATCH"):
        monkeypatch.delenv(n, raising=False)
    ns = types.SimpleNamespace(sim=sim_bridge, pdk=pdk, calls=calls, work=tmp_path / "work")
    yield ns
    for name in ("design.sim_bridge", "design.pdk"):
        sys.modules.pop(name, None)


# ------------------------------------------------------------------ where and what ----

def test_the_bridge_work_root_is_the_platforms_not_a_copy(bridge):
    assert bridge.sim.work() == bridge.work
    got = bridge.calls["work_root"]
    assert got["env"] == bridge.sim.WORK_ENV and got["repo"] == bridge.sim.REPO
    assert got["checkout"] == bridge.sim.CHECKOUT


def test_an_unset_launcher_variable_leaves_the_binary_to_the_lane(bridge, monkeypatch):
    monkeypatch.delenv(bridge.sim.LANE_ENV, raising=False)
    assert bridge.sim.simulator() == ""
    bridge.sim.run("* deck\n", "probe")
    assert "simulator" not in bridge.calls["run_deck"], "the lane package owns the command name"
    monkeypatch.setenv(bridge.sim.LANE_ENV, "/opt/launcher")
    bridge.sim.run("* deck\n", "probe")
    assert bridge.calls["run_deck"]["simulator"] == "/opt/launcher"


def test_no_mode_means_no_mode_flags(bridge, monkeypatch):
    assert bridge.sim.mode_args() == []
    monkeypatch.setattr(bridge.sim, "MODE", "ab")
    assert bridge.sim.mode_args() == ["+ab"]


def test_run_rejects_an_empty_label(bridge):
    with pytest.raises(ValueError):
        bridge.sim.run("* deck\n", "  ")


# ------------------------------------------------------------------ the token ---------

def test_run_restores_the_token_only_as_the_simulator_receives_it(bridge, monkeypatch):
    monkeypatch.setenv("XY001_PDK_LIB", "/srv/models/proc_rev_v1d0/lib.scs")
    portable = 'include "$PFX_PDK_LIB" section=tt\n'
    bridge.sim.run(portable, "op")
    assert bridge.calls["run_deck"]["deck"] == 'include "/srv/models/proc_rev_v1d0/lib.scs" section=tt\n'
    assert "$PFX_PDK_LIB" in portable, "the caller's text is untouched: what is committed stays portable"


def test_a_deck_without_the_token_never_asks_where_the_library_is(bridge):
    # no variable is set: `restore` must not raise for a deck that does not name the kit
    assert bridge.pdk.restore("* no token here\n") == "* no token here\n"


def test_models_block_names_the_token_not_a_path(bridge):
    assert bridge.pdk.models_block("tt", "core") == 'include "$PFX_PDK_LIB" section=tt'
    every = bridge.pdk.models_block()          # no groups = every declared one
    assert every.count("include") == 2 and "/" not in every


def test_a_corner_swaps_only_a_typical_section(bridge):
    assert bridge.pdk.section("core", "tt") == "tt"
    assert bridge.pdk.section("core", "ss") == "ss"
    assert bridge.pdk.section("stat", "ss") == "mis", "a statistical section carries no corner prefix"
    with pytest.raises(bridge.pdk.PdkError):
        bridge.pdk.section("core", "zz")
    with pytest.raises(bridge.pdk.PdkError):
        bridge.pdk.section("nosuch")


# ------------------------------------------------------------------ the pin -----------

def test_the_design_scoped_variable_is_read_before_the_deck_name(bridge, monkeypatch):
    monkeypatch.setenv("PFX_PDK_LIB", "/srv/shared/proc_rev_v1d0/lib.scs")
    monkeypatch.setenv("XY001_PDK_LIB", "/srv/mine/proc_rev_v1d0/lib.scs")
    assert bridge.pdk.library() == "/srv/mine/proc_rev_v1d0/lib.scs"


def test_the_per_machine_variable_is_derived_from_the_declared_process(bridge, monkeypatch):
    monkeypatch.setattr(bridge.pdk.H, "pdk", "ihp-sg13g2")
    assert bridge.pdk.machine_env() == "IHP_SG13G2_PDK_LIB"
    assert bridge.pdk.lib_envs() == ("XY001_PDK_LIB", "PFX_PDK_LIB", "IHP_SG13G2_PDK_LIB")
    monkeypatch.setenv("IHP_SG13G2_PDK_LIB", "/srv/machine/proc_rev_v1d0/lib.scs")
    assert bridge.pdk.library() == "/srv/machine/proc_rev_v1d0/lib.scs"
    monkeypatch.delenv("IHP_SG13G2_PDK_LIB")


def test_an_undeclared_process_simply_has_no_machine_variable(bridge, monkeypatch):
    monkeypatch.setattr(bridge.pdk.H, "pdk", "")
    assert bridge.pdk.machine_env() == ""
    assert bridge.pdk.lib_envs() == ("XY001_PDK_LIB", "PFX_PDK_LIB")


def test_a_value_that_does_not_carry_the_pin_is_refused_on_the_env_route(bridge, monkeypatch):
    monkeypatch.setenv("XY001_PDK_LIB", "/srv/models/proc_rev_v9d9/lib.scs")
    with pytest.raises(bridge.pdk.PdkError) as e:
        bridge.pdk.library()
    msg = str(e.value)
    assert "XY001_PDK_LIB" in msg and "proc_rev_v1d0" in msg and "ALLOW_MISMATCH" in msg
    assert "v9d9" not in msg, "a message names the variable and the pin, never the value"


def test_a_cross_revision_run_is_possible_but_has_to_be_typed(bridge, monkeypatch):
    monkeypatch.setenv("XY001_PDK_LIB", "/srv/models/proc_rev_v9d9/lib.scs")
    monkeypatch.setenv("XY001_PDK_LIB_ALLOW_MISMATCH", "1")
    assert bridge.pdk.library() == "/srv/models/proc_rev_v9d9/lib.scs"


def test_nothing_is_scanned_for_and_the_failure_names_every_variable(bridge, monkeypatch):
    monkeypatch.setattr(bridge.pdk.H, "pdk", "ihp-sg13g2")
    with pytest.raises(bridge.pdk.PdkError) as e:
        bridge.pdk.library()
    msg = str(e.value)
    for name in ("XY001_PDK_LIB", "PFX_PDK_LIB", "IHP_SG13G2_PDK_LIB"):
        assert name in msg
    assert "proc_rev_v1d0" in msg


# ------------------------------------------------------------------ doctor ------------

def test_preflight_reports_an_unresolved_library_without_simulating(bridge):
    rep = bridge.sim.preflight()
    assert rep["ok"] is False and "XY001_PDK_LIB" in rep["note"]
    assert "preflight" not in bridge.calls, "a lane that cannot bind to its process is not alive"


def test_preflight_reports_the_template_placeholders_before_anything_else(bridge, monkeypatch):
    monkeypatch.setattr(bridge.pdk, "REVISION", "<the model-library revision name>")
    assert "REVISION" in bridge.sim.preflight()["note"]
    monkeypatch.setattr(bridge.pdk, "REVISION", "proc_rev_v1d0")
    monkeypatch.setattr(bridge.pdk, "SECTIONS", {"core": "<the section>"})
    assert "SECTIONS" in bridge.sim.preflight()["note"]


def test_preflight_runs_the_probe_through_this_wrapper(bridge, monkeypatch):
    monkeypatch.setenv("XY001_PDK_LIB", "/srv/models/proc_rev_v1d0/lib.scs")
    rep = bridge.sim.preflight()
    assert rep["ok"] is True and rep["work"] == str(bridge.work)
    assert bridge.calls["preflight"]["work"] == bridge.work
    bridge.calls["preflight"]["run"]("* probe\n", "_preflight")
    assert bridge.calls["run_deck"]["timeout"] == 300, "the doctor uses this repo's own timeout"


def test_main_separates_a_missing_profile_from_a_failing_lane(bridge, monkeypatch, capsys):
    monkeypatch.setattr(bridge.sim, "preflight", lambda *a, **k: {"ok": False, "not_configured": True})
    assert bridge.sim.main() == 2, "no bridge profile is not a stop: exit 2, and say so"
    monkeypatch.setattr(bridge.sim, "preflight", lambda *a, **k: {"ok": False, "note": "x"})
    assert bridge.sim.main() == 1
    monkeypatch.setattr(bridge.sim, "preflight", lambda *a, **k: {"ok": True, "note": "x"})
    assert bridge.sim.main() == 0


def test_the_dispatcher_really_selects_the_bridge_module_when_the_key_says_so(bridge, monkeypatch):
    """Execute `design/sim.py` under a throwaway name, with `lane: bridge` in hand.

    This is the one test that runs the dispatcher's body for the bridge lane; it cannot be done by
    reloading `design.sim`, which would leave the session's `design.sim` pointing at the other lane.
    """
    import importlib.util

    import spicexplorer_harness

    monkeypatch.setattr(spicexplorer_harness, "load",
                        lambda root: types.SimpleNamespace(lane="bridge"))
    src = Path(__file__).resolve().parents[1] / "design" / "sim.py"
    spec = importlib.util.spec_from_file_location("design._lane_probe", src)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "design"
    monkeypatch.setitem(sys.modules, "design._lane_probe", mod)
    spec.loader.exec_module(mod)
    assert sys.modules["design._lane_probe"] is bridge.sim, "the swap hands over the lane module"
    assert bridge.sim.LANE == "bridge"


def test_the_bridge_module_carries_no_private_driver():
    """The wrapper wraps: nothing here may open a connection or shell out to the server."""
    src = (Path(__file__).resolve().parents[1] / "design" / "sim_bridge.py").read_text()
    for forbidden in ("import paramiko", "subprocess", "SSHClient", "scp ", "rsync"):
        assert forbidden not in src, f"{forbidden!r} belongs in the platform's lane package"
