"""The generic design modules: stimulus determinism, eye metrics on ideal and closed eyes, the lane."""

from __future__ import annotations

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from design import exp, eye, sim, stimulus


def _have_ngspice() -> bool:
    try:
        sim.ngspice()
        return True
    except FileNotFoundError:
        return False


live = pytest.mark.skipif(not _have_ngspice(), reason="no ngspice binary on this host")

# Real ngspice-45 batch log excerpts (probe decks under $SX_SCRATCH), verbatim.
LOG_INVALID_LINE = "Warning: 'r1 a 0' is not a valid resistor instance line, ignored!\ni_ma = -0.000000e+00\n"
LOG_FAILED_MEAS = ("Error: measure  bad  when(WHEN) : out of interval\n"
                   " meas tran bad when v(a)=5 failed!\n\ngood                =  1.500000e-09\n")
LOG_BAD_LET = ("Warning from checkvalid: vector nowhere is not available or has zero length.\n"
               "Error: RHS \"v(nowhere)*2\" invalid\n")


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("SX_SCRATCH", str(tmp_path))
    monkeypatch.delenv(sim.WORK_ENV, raising=False)
    return tmp_path


# ------------------------------------------------------------------ stimulus ----------

def test_prbs_is_deterministic_and_periodic():
    a, b = stimulus.prbs(7, 300), stimulus.prbs(7, 300)
    assert (a == b).all() and set(a.tolist()) == {0, 1}
    assert (a[:127] == a[127:254]).all()
    assert not (stimulus.prbs(7, 300, seed=2) == a).all()


def test_symbol_levels():
    assert set(stimulus.symbols("nrz", 7, 200).tolist()) == {-1.0, 1.0}
    assert set(np.round(stimulus.symbols("pam4", 7, 200), 6).tolist()) == {-1.0, -0.333333, 0.333333, 1.0}
    with pytest.raises(ValueError):
        stimulus.symbols("pam8", 7, 10)


def test_pwl_tap_delay_is_exact():
    d = stimulus.Data("nrz", 10.0)
    line = stimulus.pwl("Vt1", "in", "0", d, vcm=0.5, swing=0.2, delay_ui=1.0)
    assert line.startswith("Vt1 in 0 PWL(")
    pts = re.findall(r"([-+0-9.e]+) ([-+0-9.e]+)", line.split("PWL(")[1])
    first_edge = next(float(t) for t, v in pts if float(v) != 0.5)
    assert math.isclose(first_edge, d.t0 + d.ui + d.tr_ui * d.ui, rel_tol=1e-6)


# ------------------------------------------------------------------ eye ---------------

def _synthetic(fmt: str, closed: bool = False, bipolar: bool = False):
    d = stimulus.Data(fmt, 10.0, order=7, n_warm=8)
    t = np.arange(0, d.t_end + 2e-9, d.ui / 50)
    x = stimulus.ideal_waveform(t, d) if bipolar else 0.5 + 0.5 * stimulus.ideal_waveform(t, d)
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


def test_eye_bipolar_electrical_signal():
    """Levels -1/+1: OMA and VECP come from the level difference, ER is undefined (nan), not 57 dB."""
    m = eye.eye_metrics(*_synthetic("nrz", bipolar=True), full_scale=2.0)
    assert m["ok"] == 1 and 0 <= m["vecp_db"] < 3 and m["eye_h_norm"] > 0.4
    assert math.isnan(m["er_db"]) and abs(m["oma_norm"] - 2.0) < 0.2


def test_latency_is_exact_and_matches_a_direct_correlation():
    """Exact to the sample, polarity included; on a short sequence the FFT correlation picks the
    same lag as a direct bounded-lag dot product (no wall-clock assertion: shared server)."""
    d = stimulus.Data("nrz", 20.0, order=15, n_warm=8)
    dt = d.ui / eye.OVERSAMPLE
    t = np.arange(0, d.t_end + 3e-9, dt)
    delay = 37 * dt
    y = 0.3 * stimulus.ideal_waveform(t - delay, d)
    lag, sign = eye.latency(t, -y, d)
    assert sign == -1 and abs(lag - delay) < dt / 2

    d = stimulus.Data("nrz", 20.0, order=7, n_warm=2)
    dt = d.ui / 20
    t = np.arange(0, d.t_end + 3e-9, dt)
    y = 0.3 * stimulus.ideal_waveform(t - 11 * dt, d)
    ideal, yy = stimulus.ideal_waveform(t, d), y - y.mean()
    n_max = int(max(3 * d.ui, 2e-9) / dt) + 1
    direct = [float(np.dot(yy[k:], ideal[: len(ideal) - k])) for k in range(n_max)]
    assert eye.latency(t, y, d) == (int(np.argmax(np.abs(direct))) * dt, 1)


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        eye.levels("pam8")
    with pytest.raises(ValueError):
        eye.rx_bandwidth("pam8", 10.0)


# ------------------------------------------------------------------ lane: the log -----

def test_parse_measures_real_failed_meas_form():
    m, failed = sim.parse_measures(LOG_FAILED_MEAS)
    assert m == {"good": 1.5e-09} and failed == ["bad"]
    m, failed = sim.parse_measures("i_ma = 1.000000e+00\nugf = 1.2345e+06 at=  3.2\n"
                                   "Total analysis time (seconds) = 0.001\nDoing analysis at TEMP = 27.0\n")
    assert m == {"i_ma": 1.0, "ugf": 1.2345e6} and failed == []


def test_fatal_lines_classification():
    assert sim.fatal_lines(LOG_INVALID_LINE), "an ignored device line is the silent-zero class"
    assert sim.fatal_lines(LOG_BAD_LET)
    assert sim.fatal_lines("doAnalyses: iteration limit reached")
    assert sim.fatal_lines("Error on line 12 : xm1 ... Unknown model type xyz")
    assert not sim.fatal_lines(LOG_FAILED_MEAS), "a failed .meas is Run.failed, not a fatal run"
    assert not sim.fatal_lines("Warning: singular matrix:  check nodes a and b\n"
                               "Note: Starting dynamic gmin stepping\nWarning: vd: no DC value\n")


def test_spiceinit_requires_userinit_dir(tmp_path, monkeypatch):
    (tmp_path / ".spiceinit").write_text("set foo=1\n")
    monkeypatch.setenv("SPICE_USERINIT_DIR", str(tmp_path))
    monkeypatch.delenv("PDK_ROOT", raising=False)
    monkeypatch.delenv("PDK", raising=False)
    assert sim.spiceinit("echo X") == "set foo=1\necho X\n"
    env = sim._env()
    assert env["PDK"] == tmp_path.parents[1].name and env["PDK_ROOT"] == str(tmp_path.parents[2])
    (tmp_path / ".spiceinit").write_text("\n")
    with pytest.raises(FileNotFoundError, match="empty"):
        sim.spiceinit()
    monkeypatch.delenv("SPICE_USERINIT_DIR")
    with pytest.raises(FileNotFoundError):
        sim.spiceinit()
    assert sim.preflight()["ok"] is False


def test_work_dir_rules(scratch, monkeypatch):
    w = sim.work()
    assert w.parent == scratch and "<" not in w.name and w.name.endswith(sim.CHECKOUT)
    monkeypatch.setenv(sim.WORK_ENV, "/tmp/anything")
    with pytest.raises(ValueError):
        sim.work()


def test_run_rejects_empty_label(scratch):
    with pytest.raises(ValueError):
        sim.run(sim.PROBE, "")


def test_run_batch_keeps_order_and_errors():
    def score(d, tag):
        if d == 2:
            raise RuntimeError("boom")
        return {"v": d * 10}

    rows = exp.run_batch({"a": 1, "b": 2, "c": 3}, score, workers=2)
    assert [r["label"] for r in rows] == ["a", "b", "c"]
    assert rows[0]["v"] == 10 and "boom" in rows[1]["error"] and rows[2]["v"] == 30
    assert exp.md(rows, ["label", "v"]).splitlines()[2] == "| a | 10.00 |"


def test_plot_smoke(scratch):
    from design import plot

    t, x, d = _synthetic("pam4")
    m = eye.eye_metrics(t, x, d)
    p = plot.eye(t, x, d, scratch / "fig" / "eye.png", title="t", metrics={**m, "gain_db": 61},
                 keys=("gain_db", "er_db"))
    rows = [{"label": "a", "rate_gbd": r, "gain_db": 60 + r / 10, "pm_deg": 70 - r} for r in (10, 20, 40)]
    q = plot.frontier(rows, scratch / "fig" / "frontier.png", ys=("gain_db", "pm_deg"))
    assert p.stat().st_size > 1000 and q.stat().st_size > 1000


# ------------------------------------------------------------------ lane: live --------

@live
def test_preflight_simulates_one_resistor(scratch):
    info = sim.preflight()
    assert info["ok"], info
    r = sim.run(sim.PROBE, "probe")
    assert r.raw is not None and r.raw.exists() and abs(r.measures["i_ma"] - 1.0) < 1e-6 and r.rc == 0
    assert Path(r).is_dir() and (Path(r) / ".spiceinit").exists() and r.wall > 0
    assert str(r) == str(r.dir) == f"{r}"     # ledger rows store str(run); Path(run) reopens it
    assert sim.raw(r).get_trace("v(a)").get_wave()[0] == pytest.approx(1.0)


def _deck(body: str) -> str:
    return f"* p\nv1 a 0 1\nr1 a 0 1k\n.control\nop\n{body}\nwrite sim.raw\nquit\n.endc\n.end\n"


@live
def test_run_raises_on_real_errors(scratch):
    with pytest.raises(sim.SimError, match="RHS"):
        sim.run(_deck("let x = v(nowhere)*2\nprint x"), "bad_let")
    with pytest.raises(sim.SimError, match="ignored"):        # the silent-zero class
        sim.run("* p\nv1 a 0 1\nr1 a 0\n.control\nop\nlet i_ma = -i(v1)*1e3\nprint i_ma\n"
                "write sim.raw\nquit\n.endc\n.end\n", "invalid_line")
    with pytest.raises(sim.SimError, match="rc=3"):
        sim.run("* p\nv1 a 0 1\nr1 a 0 1k\n.control\nop\nlet i_ma = -i(v1)*1e3\nprint i_ma\n"
                "write sim.raw\nquit 3\n.endc\n.end\n", "rc3")
    try:
        sim.run(_deck("let x = v(nowhere)*2\nprint x"), "bad_let")
    except sim.SimError as e:
        assert str(sim.work()) not in str(e), "error text must not carry the absolute work path"


@live
def test_failed_meas_becomes_run_failed(scratch):
    r = sim.run("* p\nv1 a 0 pulse(0 1 1n 1n 1n 5n 10n)\nr1 a 0 1k\n.control\ntran 0.1n 20n\n"
                "meas tran bad when v(a)=5\nmeas tran good when v(a)=0.5 rise=1\nwrite sim.raw\nquit\n"
                ".endc\n.end\n", "failmeas")
    assert r.failed == ["bad"] and r.measures["good"] == pytest.approx(1.5e-9, rel=1e-3)


@live
def test_busy_marker_live_vs_stale(scratch):
    import os

    from spicexplorer_harness.ledger import deck_hash

    rd = sim.work() / "runs" / f"probe-{deck_hash(sim.PROBE)[:8]}"
    rd.mkdir(parents=True)
    (rd / ".busy").write_text(str(os.getpid()))            # a live owner: refuse
    with pytest.raises(sim.SimError, match="busy"):
        sim.run(sim.PROBE, "probe")
    (rd / ".busy").write_text(str(2**22 - 1))              # a dead owner (killed session): reclaim
    assert sim.run(sim.PROBE, "probe").measures["i_ma"] == pytest.approx(1.0)
    assert not (rd / ".busy").exists()


@live
def test_concurrent_runs_same_label_do_not_clobber(scratch):
    def go(rval):
        return sim.run(f"* p\nv1 a 0 1\nr1 a 0 {rval}\n.control\nop\nlet i_ma = -i(v1)*1e3\n"
                       f"print i_ma\nwrite sim.raw\nquit\n.endc\n.end\n", "same").measures["i_ma"]

    with ThreadPoolExecutor(2) as pool:
        got = list(pool.map(go, ["1k", "2k"]))
    assert got[0] == pytest.approx(1.0) and got[1] == pytest.approx(0.5)


# ------------------------------------------------------------------ scorecard ---------

class _D:
    """A two-bench Design stand-in: enough for the scorecard lifecycle, no simulator."""

    def __init__(self, corner: str = "tt"):
        self.corner = corner

    def benches(self):
        return ["b1", "b2"]

    def deck(self, bench):
        return f"* {bench}\n.end\n"

    def as_dict(self):
        return {"corner": self.corner}


def test_promote_scales_mapped_keys_and_namespaces_the_rest(monkeypatch):
    from design import metrics

    monkeypatch.setitem(metrics.KEYMAP, ("ac", "gain"), ("gain_db", 1.0))
    monkeypatch.setitem(metrics.KEYMAP, ("ac", "p"), ("power_uw", 1e6))
    got = metrics.promote("ac", {"gain": 61.0, "p": 5e-5, "stray": 2.0})
    assert got == {"gain_db": 61.0, "power_uw": pytest.approx(50.0), "ac.stray": 2.0}


def test_table_reports_pass_and_fail():
    from design import metrics

    md = metrics.table({"ok": {"gain_db": 61, "pm_deg": 70, "power_uw": 9},
                        "bad": {"gain_db": 10, "pm_deg": 70, "power_uw": 9}})
    assert "| PASS |" in md and "FAIL (1)" in md


def test_drift_limit_prefers_the_spec_tolerance_band():
    from design import metrics

    # harness.yaml gives gain_db `tolerance: {kind: abs, delta: 0.5}`; pm_deg declares none
    assert metrics.drift_limit("gain_db", 60.0) == pytest.approx(0.5)
    assert metrics.drift_limit("pm_deg", 60.0) == pytest.approx(0.6)


def test_drift_flags_moved_and_missing_columns(monkeypatch):
    from design import metrics

    monkeypatch.setattr(metrics, "certified", lambda: {"scorecard": {"gain_db": 60.0, "pm_deg": 70.0}})
    got = dict(sorted((k, why) for k, _g, _w, why in
                      metrics.drift({"gain_db": 60.4, "pm_deg": float("nan")})))
    assert "gain_db" not in got                       # inside the 0.5 band
    assert got["pm_deg"] == "NOT MEASURED"
    assert [k for k, *_ in metrics.drift({"gain_db": 61.0, "pm_deg": 70.0})] == ["gain_db"]


@pytest.fixture
def _certify_env(monkeypatch):
    from design import metrics

    rows: list[dict] = []
    monkeypatch.setattr(metrics, "run_decks",
                        lambda decks, tag, record=True: ({"gain_db": 61.0, "pm_deg": 70.0,
                                                          "power_uw": 9.0, "dead": float("nan")},
                                                         {b: {"status": "ok", "measures": {}} for b in decks}))
    monkeypatch.setattr(metrics, "log_run", lambda h, tag, values, **kw: rows.append({"tag": tag, **kw}))
    return metrics, rows


def test_certify_unsigned_writes_no_provenance_block(_certify_env, tmp_path):
    metrics, rows = _certify_env
    doc = metrics.certify(_D(), tag="t", out=tmp_path)
    # a provenance block with no signed row behind it is a lint failure nobody can green
    assert "provenance" not in doc and "tag" not in doc
    assert rows[0].get("evidence", "scratch") == "scratch"
    assert set(doc["scorecard"]) == {"gain_db", "pm_deg", "power_uw"}   # NaN dropped
    assert (tmp_path / "b1.spice").exists() and (tmp_path / "decks.sha256").exists()


def test_certify_signed_block_recomputes_and_matches_its_row(_certify_env, tmp_path):
    from spicexplorer_harness import hashes

    metrics, rows = _certify_env
    doc = metrics.certify(_D(), tag="t", out=tmp_path, author="designer", verified_by="verifier")
    prov = doc["provenance"]
    assert doc["tag"] == "t" and doc["corner"] == "tt"           # the keys _backing_rows matches on
    assert hashes.recompute(metrics.H.root, prov, values=doc["scorecard"]) == []
    row = rows[0]
    assert row["evidence"] == "signed" and row["verified_by"] == "verifier"
    assert all(row[k] == prov[k] for k in hashes.HASH_KEYS)


# ------------------------------------------------------------------ lint + layout -----

def _load(rel: str):
    import importlib.util

    path = Path(__file__).resolve().parents[1] / rel
    spec = importlib.util.spec_from_file_location(path.stem + "_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_lint_extras_are_green_on_the_bare_template():
    from spicexplorer_harness import load
    from spicexplorer_harness.lint import Lint

    mod = _load("scripts/lint.py")
    L = Lint(load(Path(__file__).resolve().parents[1]))
    for check in mod.EXTRA:
        check(L)
    assert L.fails == []


def test_drc_violation_serializer_never_crashes_on_a_real_violation():
    class V:  # what a runner returns: not JSON-serialisable, and only ever non-empty on a FAIL
        def __init__(self, rule):
            self.rule = rule

    signoff = _load("layout/signoff.py")
    counts = signoff.violation_counts([V("M1.b"), V("M1.b"), V("V1.a"), {"rule": "M1.b"}, object()])
    assert counts == {"M1.b": 3, "V1.a": 1, "?": 1}
    assert json.loads(json.dumps(counts)) == counts
    assert signoff.violation_counts([]) == {} and signoff.violation_counts(None) == {}


def test_gds_python_refuses_a_default_home_path(monkeypatch):
    signoff = _load("layout/signoff.py")
    monkeypatch.delenv(signoff.GDS_PYTHON_ENV, raising=False)
    with pytest.raises(SystemExit) as e:
        signoff.gds_python()
    assert signoff.GDS_PYTHON_ENV in str(e.value) and "FIX:" in str(e.value)


def test_a_signed_certification_greens_scorecard_recompute(monkeypatch, tmp_path):
    """End to end: what `certify(--author --verified-by)` writes is what the lint accepts.

    The LDO instantiation shipped a scorecard whose `scorecard-recompute` no signature could
    ever green. This is the demonstration that the gate CAN go green — a gate whose passing
    condition has never been shown is an assumption, not a gate.
    """
    import shutil

    from spicexplorer_harness import load
    from spicexplorer_harness.lint import Lint, scorecard_recompute

    from design import metrics

    repo = Path(__file__).resolve().parents[1]
    (tmp_path / "design").mkdir()
    shutil.copy(repo / "design" / "metrics.py", tmp_path / "design" / "metrics.py")
    (tmp_path / "harness.yaml").write_text(
        "name: t\nfrozen: [decks/reference]\n"
        "reference_scorecard: decks/reference/scorecard.json\n"
        "verifiers: [verifier]\n"
        'spec:\n  - {key: gain_db, label: gain, op: ">=", bound: 60, unit: dB}\n')
    h = load(tmp_path)
    monkeypatch.setattr(metrics, "H", h)
    monkeypatch.setattr(metrics, "run_decks",
                        lambda decks, tag, record=True: ({"gain_db": 61.0},
                                                         {b: {"status": "ok", "measures": {}} for b in decks}))
    metrics.certify(_D(), tag="ref", out=tmp_path / "decks" / "reference",
                    author="designer", verified_by="verifier")

    L = Lint(h)
    scorecard_recompute(L)
    assert L.fails == []

    # and a hand-edited number is caught: the value is inside the computation hash
    card = json.loads((tmp_path / "decks/reference/scorecard.json").read_text())
    card["scorecard"]["gain_db"] = 99.0
    (tmp_path / "decks/reference/scorecard.json").write_text(json.dumps(card))
    L2 = Lint(load(tmp_path))
    scorecard_recompute(L2)
    assert L2.fails
