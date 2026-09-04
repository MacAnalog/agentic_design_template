"""The generic lab modules: stimulus determinism, eye metrics on ideal and closed eyes, the lane."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from lab import exp, eye, sim, stimulus


def _have_ngspice() -> bool:
    try:
        sim.ngspice()
        return True
    except FileNotFoundError:
        return False


# ------------------------------------------------------------------ stimulus ----------

def test_prbs_is_deterministic_and_periodic():
    a, b = stimulus.prbs(7, 300), stimulus.prbs(7, 300)
    assert (a == b).all() and set(a.tolist()) == {0, 1}
    assert (a[:127] == a[127:254]).all()
    assert not (stimulus.prbs(7, 300, seed=2) == a).all()


def test_symbol_levels():
    assert set(stimulus.symbols("nrz", 7, 200).tolist()) == {-1.0, 1.0}
    assert set(np.round(stimulus.symbols("pam4", 7, 200), 6).tolist()) == {-1.0, -0.333333, 0.333333, 1.0}


def test_pwl_tap_delay_is_exact():
    d = stimulus.Data("nrz", 10.0)
    line = stimulus.pwl("Vt1", "in", "0", d, vcm=0.5, swing=0.2, delay_ui=1.0)
    assert line.startswith("Vt1 in 0 PWL(")
    pts = re.findall(r"([-+0-9.e]+) ([-+0-9.e]+)", line.split("PWL(")[1])
    first_edge = next(float(t) for t, v in pts if float(v) != 0.5)
    assert math.isclose(first_edge, d.t0 + d.ui + d.tr_ui * d.ui, rel_tol=1e-6)


# ------------------------------------------------------------------ eye ---------------

def _synthetic(fmt: str, closed: bool = False):
    d = stimulus.Data(fmt, 10.0, order=7, n_warm=8)
    t = np.arange(0, d.t_end + 2e-9, d.ui / 50)
    x = 0.5 + 0.5 * stimulus.ideal_waveform(t, d)          # unipolar, 0..1
    if closed:
        x = 0.5 + 0.02 * np.random.default_rng(0).standard_normal(t.size)
    return t, x, d


@pytest.mark.parametrize("fmt,h_min", [("nrz", 0.4), ("pam4", 0.1)])
def test_eye_ideal_is_open(fmt, h_min):
    m = eye.eye_metrics(*_synthetic(fmt))
    assert m["ok"] == 1 and m["eye_h_norm"] > h_min and m["eye_w_ui"] > 0.5 and m["vecp_db"] < 6
    assert m["er_db"] > 10 and m["polarity"] == 1
    assert all(math.isfinite(v) for v in m.values() if isinstance(v, float))
    json.dumps(m)  # plain floats only, so rows land in the ledger


@pytest.mark.parametrize("fmt", ["nrz", "pam4"])
def test_eye_closed_is_finite(fmt):
    m = eye.eye_metrics(*_synthetic(fmt, closed=True))
    assert m["eye_h_norm"] <= 0 and m["eye_w_ui"] == 0 and m["vecp_db"] == eye.VECP_CAP_DB
    assert all(math.isfinite(v) for v in m.values() if isinstance(v, float))


# ------------------------------------------------------------------ lane --------------

def test_parse_measures():
    log = ("i_ma = 1.000000e+00\nugf = 1.2345e+06 at=  3.2\nbad = failed\n"
           "Total analysis time (seconds) = 0.001\nDoing analysis at TEMP = 27.0\n")
    m, failed = sim.parse_measures(log)
    assert m == {"i_ma": 1.0, "ugf": 1.2345e6} and failed == ["bad"]


def test_fatal_lines():
    assert sim.fatal_lines("Error: no such vector as x")
    assert sim.fatal_lines("doAnalyses: iteration limit reached")
    assert sim.fatal_lines("Error on line 12 : xm1 ... Unknown model type psp103va")
    assert not sim.fatal_lines("Warning: vd: no DC value\nNote: Starting dynamic gmin stepping\n")


def test_spiceinit_and_pdk_env_from_userinit_dir(tmp_path, monkeypatch):
    (tmp_path / ".spiceinit").write_text("set foo=1\n")
    monkeypatch.setenv("SPICE_USERINIT_DIR", str(tmp_path))
    monkeypatch.delenv("PDK_ROOT", raising=False)
    monkeypatch.delenv("PDK", raising=False)
    assert sim.spiceinit("echo X") == "set foo=1\necho X\n"
    env = sim._env()
    assert env["PDK"] == tmp_path.parents[1].name and env["PDK_ROOT"] == str(tmp_path.parents[2])


def test_work_dir_under_scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("SX_SCRATCH", str(tmp_path))
    monkeypatch.delenv(sim.WORK_ENV, raising=False)
    w = sim.work()
    assert w.parent == tmp_path and "<" not in w.name and w.name.endswith(sim.CHECKOUT)


def test_run_batch_keeps_order_and_errors():
    def score(d, tag):
        if d == 2:
            raise RuntimeError("boom")
        return {"v": d * 10}

    rows = exp.run_batch({"a": 1, "b": 2, "c": 3}, score, workers=2)
    assert [r["label"] for r in rows] == ["a", "b", "c"]
    assert rows[0]["v"] == 10 and "boom" in rows[1]["error"] and rows[2]["v"] == 30
    assert exp.md(rows, ["label", "v"]).splitlines()[2] == "| a | 10.00 |"


@pytest.mark.skipif(not _have_ngspice(), reason="no ngspice binary on this host")
def test_preflight_simulates_one_resistor(tmp_path, monkeypatch):
    monkeypatch.setenv("SX_SCRATCH", str(tmp_path))
    monkeypatch.delenv(sim.WORK_ENV, raising=False)
    info = sim.preflight()
    assert info["ok"], info
    r = sim.run(sim.PROBE, "probe")
    assert r.raw is not None and r.raw.exists() and abs(r.measures["i_ma"] - 1.0) < 1e-6
    assert Path(r).is_dir() and (Path(r) / ".spiceinit").exists() and r.wall > 0
    assert str(r) == str(r.dir) == f"{r}"     # ledger rows store str(run); Path(run) reopens it
    assert sim.raw(r).get_trace("v(a)").get_wave()[0] == pytest.approx(1.0)
    with pytest.raises(sim.SimError):
        sim.run("* bad\nv1 a 0 1\nr1 a 0 1k\n.control\nop\nprint v(nowhere)\n.endc\n.end\n", "bad")
