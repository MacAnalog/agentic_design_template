"""The generic design modules: the simulator lane, batches, plots and the scorecard lifecycle."""

from __future__ import annotations

import json
import sys
import types
import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from design import exp, sim


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


def test_resolve_substitutes_declared_names_only(monkeypatch):
    """`$` opens a comment in some dialects, so only DECK_VARS names may ever be expanded."""
    monkeypatch.setattr(sim, "DECK_VARS", ("MODEL_LIB",))
    monkeypatch.setenv("MODEL_LIB", "/opt/site/models/lib.file")
    deck = 'include "$MODEL_LIB" section=tt\n* $NOT_DECLARED stays verbatim\n'

    out = sim.resolve(deck)
    assert 'include "/opt/site/models/lib.file" section=tt' in out
    assert "$NOT_DECLARED" in out and "$MODEL_LIB" not in out

    monkeypatch.delenv("MODEL_LIB")
    with pytest.raises(FileNotFoundError, match="MODEL_LIB"):
        sim.resolve(deck)
    assert sim.resolve("* no placeholder here\n") == "* no placeholder here\n"
    assert sim.preflight()["ok"] is False, "a lane that cannot resolve a declared var is not alive"


def test_the_design_scoped_variable_is_read_before_the_shared_one(monkeypatch):
    """The bare name is the text inside every frozen deck, so it is shared by construction; one
    export of it in one shell profile can feed two repos (macanalog-design-directory#38)."""
    monkeypatch.setattr(sim, "DECK_VARS", ("MODEL_LIB",))
    monkeypatch.setattr(sim, "DECK_VAR_SCOPE", "DN999")
    monkeypatch.setenv("MODEL_LIB", "/opt/site/models/other.file")
    monkeypatch.setenv("DN999_MODEL_LIB", "/opt/site/models/mine.file")
    assert sim.deck_var_names("MODEL_LIB") == ("DN999_MODEL_LIB", "MODEL_LIB")
    assert "mine.file" in sim.resolve('include "$MODEL_LIB"\n')

    monkeypatch.delenv("DN999_MODEL_LIB")          # every candidate is tried before failing
    assert "other.file" in sim.resolve('include "$MODEL_LIB"\n')

    monkeypatch.delenv("MODEL_LIB")
    with pytest.raises(FileNotFoundError, match="DN999_MODEL_LIB"):
        sim.resolve('include "$MODEL_LIB"\n')


def test_a_pinned_variable_may_not_point_at_another_revision(monkeypatch):
    """The revision is the one input to reproducing a certified scorecard that is NOT committed,
    so an unchecked export turns a wrong path into a full green `make check`."""
    monkeypatch.setattr(sim, "DECK_VARS", ("MODEL_LIB",))
    monkeypatch.setattr(sim, "DECK_VAR_PINS", {"MODEL_LIB": "rev_v1d0"})
    deck = 'include "$MODEL_LIB"\n'

    monkeypatch.setenv("MODEL_LIB", "/opt/site/models/rev_v9d9.file")
    with pytest.raises(sim.DeckVarError) as e:
        sim.resolve(deck)
    assert "rev_v1d0" in str(e.value) and "rev_v9d9" not in str(e.value)  # never echo the value

    monkeypatch.setenv("MODEL_LIB_ALLOW_MISMATCH", "1")   # deliberate, and it has to be typed
    assert "rev_v9d9" in sim.resolve(deck)

    monkeypatch.delenv("MODEL_LIB_ALLOW_MISMATCH")
    monkeypatch.setenv("MODEL_LIB", "/opt/site/models/rev_v1d0.file")
    assert "rev_v1d0" in sim.resolve(deck)


def test_an_unpinned_variable_keeps_substituting_whatever_it_is_given(monkeypatch):
    """`DECK_VAR_PINS` is opt-in: a design that declared only `DECK_VARS` is unaffected."""
    monkeypatch.setattr(sim, "DECK_VARS", ("MODEL_LIB",))
    monkeypatch.setenv("MODEL_LIB", "/opt/site/models/anything.file")
    assert "anything.file" in sim.resolve('include "$MODEL_LIB"\n')


def test_run_resolves_the_deck_only_as_the_simulator_receives_it(scratch, monkeypatch):
    """What is built, logged, frozen and diffed stays portable; the path exists for one call."""
    seen = {}

    class _R:
        raws, measures, failed = ["sim.raw"], {"i_ma": 1.0}, []

    monkeypatch.setattr(sim, "DECK_VARS", ("MODEL_LIB",))
    monkeypatch.setenv("MODEL_LIB", "/opt/site/models/lib.file")
    monkeypatch.setattr(sim, "spiceinit", lambda extra="": "set x\n")
    monkeypatch.setattr(sim, "ngspice", lambda: "/bin/true")
    def _fake_run_deck(deck, **kw):
        seen["deck"] = deck
        return _R()

    monkeypatch.setattr(sim, "run_deck", _fake_run_deck)

    portable = 'include "$MODEL_LIB"\n.end\n'
    sim.run(portable, "t")
    assert seen["deck"] == 'include "/opt/site/models/lib.file"\n.end\n'
    assert portable == 'include "$MODEL_LIB"\n.end\n', "the caller's deck text is not mutated"


def test_run_batch_keeps_order_and_errors():
    def score(d, tag):
        if d == 2:
            raise RuntimeError("boom")
        return {"v": d * 10}

    rows = exp.run_batch({"a": 1, "b": 2, "c": 3}, score, workers=2)
    assert [r["label"] for r in rows] == ["a", "b", "c"]
    assert rows[0]["v"] == 10 and "boom" in rows[1]["error"] and rows[2]["v"] == 30
    assert exp.md(rows, ["label", "v"]).splitlines()[2] == "| a | 10.00 |"


def test_csv_columns_are_the_union_in_first_seen_order(scratch):
    """An arm that measured one extra key must not silently lose it (template 2.00, `tables/`)."""
    out = exp.csv([{"label": "a", "g": 1.0}, {"label": "b", "g": 2.0, "x": 3}], scratch / "t.csv")
    head, *body = out.read_text().splitlines()
    assert head == "label,g,x"
    assert body == ["a,1.0,", "b,2.0,3"]


def test_plot_smoke(scratch):
    """`plot.series` for any design; `plot.eye` for the ones that carry data.

    The eye machinery is the platform's — this proves the drawing code still talks to it after the
    template stopped shimming `stimulus`/`eye` into the design package (template 2.00).
    """
    from spicexplorer_waveview import eye as wv_eye
    from spicexplorer_waveview import stimulus as wv_stim

    from design import plot

    d = wv_stim.Data("pam4", 10.0, order=7, n_warm=8)
    t = np.arange(0, d.t_end + 2e-9, d.ui / 50)
    x = 0.5 + 0.5 * wv_stim.ideal_waveform(t, d)
    m = wv_eye.eye_metrics(t, x, d)
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


def test_keymap_promotes_every_key_the_package_reduction_produces(monkeypatch):
    """The reduction's keys reach the scorecard un-namespaced — that is what `PRODUCES` declares."""
    from design import bench

    monkeypatch.setattr(bench, "PRODUCES", {"stb": ("pm_deg", "ugf_mhz")})
    assert bench.keymap() == {("stb", "pm_deg"): ("pm_deg", 1.0),
                              ("stb", "ugf_mhz"): ("ugf_mhz", 1.0)}
    assert bench.reduce("stb", object()) == {}, "the bare template reduces nothing"


def test_run_decks_records_the_package_reduction_beside_the_printed_scalars(monkeypatch):
    """A post-processed number is certifiable ONLY because it is merged here, before `certify`
    freezes the record — the same maths in an experiment's run.py would reach nothing."""
    from design import metrics

    class _R:
        measures, failed, wall = {"i_supply": 5e-5}, [], 0.1

    monkeypatch.setattr(metrics.sim, "run", lambda deck, tag: _R())
    monkeypatch.setattr(metrics, "log_run", lambda *a, **k: None)
    monkeypatch.setattr(metrics.bench_mod, "reduce", lambda b, r: {"pm_deg": 61.0})
    monkeypatch.setitem(metrics.KEYMAP, ("stb", "pm_deg"), ("pm_deg", 1.0))

    values, records = metrics.run_decks({"stb": "* stb\n.end\n"}, "t")
    assert values["pm_deg"] == 61.0                      # promoted as a column
    assert values["stb.i_supply"] == 5e-5                # printed scalar kept, namespaced
    assert records["stb"]["measures"]["pm_deg"] == 61.0  # and it is in what certify freezes


def test_a_deck_that_simulated_but_did_not_measure_is_not_an_ok_bench(monkeypatch):
    """A `.meas` that failed prints no number: `promote` makes it NaN, `certify()` drops NaNs from
    the card and `drift()` iterates the CERTIFIED keys — so an `ok` bench here is exactly how a
    spec column disappears from the frozen reference and is never missed again."""
    from design import metrics

    class _R:
        measures, failed, wall = {"gain_db": 61.0}, ["pm_deg"], 0.1

    monkeypatch.setattr(metrics.sim, "run", lambda deck, tag: _R())
    monkeypatch.setattr(metrics, "log_run", lambda *a, **k: None)
    values, records = metrics.run_decks({"ac": "* ac\n.end\n"}, "t")
    assert records["ac"]["status"] != "ok", "the deck ran; its measure did not"
    assert records["ac"]["failed"] == ["pm_deg"]
    # the measures that DID come out are still promoted, and the failed one is still NaN
    assert values["ac.gain_db"] == 61.0 and math.isnan(values["ac.pm_deg"])


def _scored(values: dict):
    """A `score` for the lifecycle: these values, every bench `ok`.

    Keyed by the deck's stem, because the lifecycle hands over FILE names — those are the bytes it
    freezes — while a record and the KEYMAP speak bench names.
    """

    def score(decks, tag, record=True):
        return dict(values), {Path(b).stem: {"status": "ok", "measures": {}} for b in decks}

    return score


def test_certify_refuses_a_reference_whose_measure_failed(monkeypatch, tmp_path):
    """The end of the same path: the deck simulates, one measure fails, and the certification used
    to be written with that column simply absent."""
    from design import metrics

    class _R:
        measures, failed, wall = {"gain_db": 61.0}, ["pm_deg"], 0.1

    from spicexplorer_harness import lifecycle as LC

    monkeypatch.setattr(metrics.sim, "run", lambda deck, tag: _R())
    monkeypatch.setattr(metrics.bench_mod, "reduce", lambda bench, r: {})
    monkeypatch.setattr(metrics, "log_run", lambda *a, **k: None)
    monkeypatch.setattr(LC, "log_run", lambda *a, **k: None)
    with pytest.raises(metrics.CertifyRefused, match="pm_deg"):
        metrics.certify(_D(), tag="t", out=tmp_path)
    assert not list(tmp_path.glob("scorecard.json")), "no scorecard may be written"


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
    """A column that did not come back is `NOT MEASURED`, never skipped — the second half of
    AT-01. `drift()` returns `Drift` records now (the lifecycle's), not tuples."""
    from design import metrics

    monkeypatch.setattr(type(metrics.L), "certified_card",
                        lambda self: {"scorecard": {"gain_db": 60.0, "pm_deg": 70.0}})
    got = {d.key: d.why for d in metrics.drift({"gain_db": 60.4, "pm_deg": float("nan")})}
    assert "gain_db" not in got                       # inside the 0.5 band
    assert got["pm_deg"] == "NOT MEASURED"
    assert [d.key for d in metrics.drift({"gain_db": 61.0, "pm_deg": 70.0})] == ["gain_db"]


@pytest.fixture
def _certify_env(monkeypatch):
    """A certification over fake simulation.

    The lifecycle is the harness's now, so the fixture patches what this design supplies — the
    SIMULATOR — and not `run_decks`: `Lifecycle` holds a reference to the real function and would
    never see a module-level replacement. The ledger is patched in both places a row is written
    from (`metrics.run_decks` writes the bench rows, `lifecycle` the evaluate/signed ones), so a
    test never appends to the repo's own ledger.
    """
    from spicexplorer_harness import lifecycle as LC

    from design import metrics

    class _R:
        measures = {"gain_db": 61.0, "pm_deg": 70.0, "power_uw": 9.0, "dead": float("nan")}
        failed: list[str] = []
        wall = 0.1

    rows: list[dict] = []

    def _log(h, tag, values, **kw):
        rows.append({"tag": tag, **kw})
        return dict(values)

    monkeypatch.setattr(metrics.sim, "run", lambda deck, tag: _R())
    monkeypatch.setattr(metrics.bench_mod, "reduce", lambda bench, r: {})
    monkeypatch.setattr(metrics, "log_run", lambda *a, **k: None)   # the per-bench rows
    monkeypatch.setattr(LC, "log_run", _log)
    return metrics, rows


def test_certify_unsigned_writes_no_provenance_block(_certify_env, tmp_path):
    metrics, rows = _certify_env
    doc = metrics.certify(_D(), tag="t", out=tmp_path).doc     # a CertifyResult now, not a dict
    # The shared lifecycle ALWAYS writes the provenance block, and always logs the row that backs
    # it — `evidence: awaiting`, the delivery claim. That is the difference from the copy this
    # replaced, and it is the fix for the trap the LDO hit: a block with no row behind it was a
    # `scorecard-recompute` failure no reader could ever green. Signing adds a second row; it does
    # not create the block.
    assert doc["provenance"]["script_sha"] and doc["tag"] == "t"
    assert "verified_by" not in doc["provenance"]
    # unlisted measures keep their `<bench>.<measure>` name (the template ships an empty KEYMAP),
    # and the NaN column — a measure that failed — never reaches the card
    assert set(doc["scorecard"]) == {f"{b}.{m}" for b in ("b1", "b2")
                                     for m in ("gain_db", "pm_deg", "power_uw")}
    assert (tmp_path / "b1.spice").exists() and (tmp_path / "decks.sha256").exists()


def test_certify_signed_block_recomputes_and_matches_its_row(_certify_env, tmp_path):
    from spicexplorer_harness import hashes

    metrics, rows = _certify_env
    doc = metrics.certify(_D(), tag="t", out=tmp_path,
                          author="designer", verified_by="verifier").doc
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


_DUT_SRC = '''
import dataclasses

@dataclasses.dataclass(frozen=True)
class Design:
    topology: str = "t"
    stub: bool = False
    def benches(self): return ["op"]
    def deck(self, bench):
        if self.stub:
            raise NotImplementedError(bench)
        return f"* {self.topology} {bench}\\n"
    def as_dict(self): return dataclasses.asdict(self)
    @classmethod
    def from_dict(cls, d):
        f = {x.name for x in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in f})

REFERENCE = Design()
'''

_HARNESS_SRC = """
name: ldo
package: ldo
exp_env: LDO_EXP
jobs_env: LDO_JOBS
sim_env: NGSPICE_BIN
spec_doc: doc/target-spec.md
reference_scorecard: decks/reference/scorecard.json
frozen: [decks/stubbed, decks/reference]
verifiers: [owner, signoff-verifier]
spec:
  - {key: gain_db, label: gain, op: ">=", bound: 60, unit: dB}
"""


@pytest.fixture(scope="module")
def renamed_repo(tmp_path_factory):
    """A checkout after the instantiation rename: `package: ldo`, no `design/` anywhere.

    Module-scoped and single-named on purpose — `sys.modules["ldo"]` caches the first tree, so a
    second fixture building another `ldo/` would silently test the wrong one.
    """
    import shutil

    root = tmp_path_factory.mktemp("renamed")
    src = Path(__file__).resolve().parents[1] / "design"
    pkg = root / "ldo"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for f in ("sim.py", "metrics.py", "bench.py"):   # metrics imports the reduction module
        shutil.copy(src / f, pkg / f)
    (pkg / "dut.py").write_text(_DUT_SRC)
    (root / "harness.yaml").write_text(_HARNESS_SRC)
    (root / "doc").mkdir()
    for rel, design in (("decks/stubbed", {"stub": True}), ("decks/reference", {"topology": "t"})):
        d = root / rel
        d.mkdir(parents=True)
        (d / "design.json").write_text(json.dumps(design))
        (d / "op.spice").write_text("* WAS CERTIFIED FROM AN OLDER BUILDER\n")
    sys.path.insert(0, str(root))
    yield root
    sys.path.remove(str(root))
    for name in [k for k in sys.modules if k == "ldo" or k.startswith("ldo.")]:
        del sys.modules[name]


def test_signed_certify_survives_the_rename(renamed_repo, monkeypatch, tmp_path):
    """`provenance(script=…)` hashes the scorer. A literal `design/metrics.py` names a file that
    the rename this template PRESCRIBES has just moved — and only a SIGNED certify ever notices."""
    import importlib

    metrics = importlib.import_module("ldo.metrics")
    assert metrics.SCRIPT == "ldo/metrics.py" and (renamed_repo / metrics.SCRIPT).is_file()
    import dataclasses

    from spicexplorer_harness import lifecycle as LC
    monkeypatch.setattr(LC, "log_run", lambda h, tag, values, **kw: dict(values))
    from ldo.dut import Design

    # the lifecycle holds its inputs, so a test swaps THEM — patching `metrics.run_decks` would
    # replace a module attribute the shared implementation never reads
    lc = dataclasses.replace(metrics.L, score=_scored({"gain_db": 62.4}))
    doc = lc.certify(Design(), tag="t", out=tmp_path,
                     author="owner", verified_by="signoff-verifier").doc
    assert doc["provenance"]["script_sha"]


def test_deck_rebuild_resolves_the_package_from_harness_yaml(renamed_repo):
    """The check that catches a half-finished rename must not itself be broken BY the rename —
    and one un-implemented frozen dir must not skip every dir after it (`continue`, not `return`)."""
    from spicexplorer_harness import load
    from spicexplorer_harness.lint import Lint

    mod = _load("scripts/lint.py")
    L = Lint(load(renamed_repo))
    mod.deck_rebuild(L)
    assert len(L.fails) == 1 and "decks/reference" in L.fails[0]     # the stubbed dir was skipped
    assert "No module named 'design'" not in L.fails[0]


def test_spec_quotes_needs_the_certified_precision_not_a_substring(renamed_repo):
    from spicexplorer_harness import load
    from spicexplorer_harness.lint import Lint

    mod = _load("scripts/lint.py")
    card = renamed_repo / "decks/reference/scorecard.json"
    card.write_text(json.dumps({"scorecard": {"gain_db": 62.4}}))
    doc = renamed_repo / "doc/target-spec.md"
    for text, quoted in (("| gain | >= 60 dB | 62 | (over 1620 samples)", False),
                         ("| gain | >= 60 dB | 62.4 |", True),
                         ("| gain | >= 60 dB | 62.40 |", True)):   # {:.2f}, only at |v| >= 1
        doc.write_text(text + "\n")
        L = Lint(load(renamed_repo))
        mod.spec_quotes(L)
        assert (L.fails == []) is quoted, text
        assert quoted or L.fails[0].startswith("[spec-quotes]")      # not the platform's spec-sync


def test_spec_quotes_matches_the_rows_own_line_not_the_whole_document(renamed_repo):
    """AT-04: every number in the doc went into ONE set, so a baseline column holding the WRONG
    value passed whenever the certified number happened to appear anywhere else in the file."""
    from spicexplorer_harness import load
    from spicexplorer_harness.lint import Lint

    mod = _load("scripts/lint.py")
    (renamed_repo / "decks/reference/scorecard.json").write_text(
        json.dumps({"scorecard": {"gain_db": 62.4}}))
    doc = renamed_repo / "doc/target-spec.md"
    doc.write_text("| gain | >= 60 dB | 58.1 |\n\n"
                   "An earlier build measured 62.4 dB; the table above is the one that counts.\n")
    L = Lint(load(renamed_repo))
    mod.spec_quotes(L)
    assert L.fails and L.fails[0].startswith("[spec-quotes]"), \
        "62.4 appears only in prose; the gain row quotes 58.1"


def test_spec_quotes_says_so_when_no_row_names_the_key(renamed_repo):
    """A row the doc never names cannot be checked — and silence there is what let the
    document-wide match stand in for a per-row one."""
    from spicexplorer_harness import load
    from spicexplorer_harness.lint import Lint

    mod = _load("scripts/lint.py")
    (renamed_repo / "decks/reference/scorecard.json").write_text(
        json.dumps({"scorecard": {"gain_db": 62.4}}))
    (renamed_repo / "doc/target-spec.md").write_text("| S9 | slew rate | >= 1 V/us | 62.4 |\n")
    L = Lint(load(renamed_repo))
    mod.spec_quotes(L)
    assert L.fails and "names" in L.fails[0]


def test_certify_refuses_to_write_a_reference_missing_a_bench(_certify_env, monkeypatch, tmp_path):
    """A frozen dir born without a bench is one `make freeze` from being sha-locked, and `drift()`
    iterates the CERTIFIED keys — so the missing column can never be noticed again."""
    import dataclasses

    metrics, _rows = _certify_env

    def score(decks, tag, record=True):
        return ({"gain_db": 61.0},
                {Path(b).stem: {"status": "ok" if Path(b).stem == "b1" else "sim_error",
                                "measures": {}} for b in decks})

    lc = dataclasses.replace(metrics.L, score=score, reference=_D())
    with pytest.raises(metrics.CertifyRefused, match="b2"):
        lc.certify(_D(), tag="t", out=tmp_path)
    assert not list(tmp_path.glob("scorecard.json"))          # the card a drift check reads
    monkeypatch.setattr(type(lc), "frozen_dir", lambda self: tmp_path)
    assert lc.main(["--certify"]) == 1                        # and the CLI exits non-zero
    assert lc.main(["--certify", "--force"]) == 0             # deliberately partial, on request


def test_deck_portable_spots_a_committed_absolute_include():
    """Two designs froze a deck carrying a machine-specific library path; `$VAR` is the fix."""
    mod = _load("scripts/lint.py")
    assert mod.abs_includes('include "/opt/site/models/lib.file" section=tt\n') == [
        "/opt/site/models/lib.file"]
    assert mod.abs_includes('.include /opt/site/models/nmos.spice\n') == ["/opt/site/models/nmos.spice"]
    assert mod.abs_includes('include "$MODEL_LIB" section=tt\n'
                            '.include ../models/nmos.spice\n'
                            '* /opt/site/models/lib.file named in a comment is not an include\n') == []


def _staged_repo(tmp_path, files: dict[str, str]):
    """A minimal git checkout with `files` staged. `artifact_home` reads `git ls-files`."""
    import subprocess as sp

    root = tmp_path / "r"
    root.mkdir()
    (root / "harness.yaml").write_text(_HARNESS_SRC)
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    sp.run(["git", "init", "-q"], cwd=root, check=True)
    sp.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def _lint_on(root):
    from spicexplorer_harness import load
    from spicexplorer_harness.lint import Lint

    return _load("scripts/lint.py"), Lint(load(root))


def test_artifact_home_refuses_an_undeclared_directory_and_accepts_the_declared_ones(tmp_path):
    """A figure nobody can find is a claim nobody can check (template 2.00)."""
    root = _staged_repo(tmp_path, {
        "experiments/003-sizing/figs/sweep.png": "x",     # the working space: fine
        "experiments/003-sizing/scratch/look.png": "x",   # still inside experiments/: fine
        "signoff/prelayout/figs/pm.png": "x",             # the design of record: fine
        "doc/figs/block.svg": "x",
        "layout/cell/iterations/it3.png": "x",            # the generator's own output: fine
        "report/round4/eye.png": "x",                     # nobody declared `report/`
    })
    mod, L = _lint_on(root)
    mod.artifact_home(L)
    assert len(L.fails) == 1, L.fails
    assert "report/" in str(L.fails[0]) and "report/round4/eye.png" in str(L.fails[0])
    assert "ARTIFACT_HOMES" in str(L.fails[0])            # the fix names the escape hatch


def test_artifact_home_reports_one_failure_per_directory_not_per_file(tmp_path):
    """A design with a physics lane has hundreds; 248 failure blocks is a lint nobody reads."""
    root = _staged_repo(tmp_path, {f"physics/out/s{i}.csv": "x" for i in range(40)})
    mod, L = _lint_on(root)
    mod.artifact_home(L)
    assert len(L.fails) == 1, L.fails
    assert "40 files" in str(L.fails[0]) and "physics/" in str(L.fails[0])


def test_artifact_home_declares_a_designs_own_home(tmp_path, monkeypatch):
    """The escape hatch is a declaration, not an exemption: one line, and the check passes."""
    root = _staged_repo(tmp_path, {"physics/out/sweep.csv": "x"})
    mod, L = _lint_on(root)
    monkeypatch.setattr(mod, "ARTIFACT_HOMES", (*mod.ARTIFACT_HOMES, "physics/"))
    mod.artifact_home(L)
    assert L.fails == []


def test_signoff_index_refuses_an_undescribed_fidelity(tmp_path):
    """An unlisted directory in the trusted tree looks certified and says nothing."""
    root = _staged_repo(tmp_path, {
        "signoff/README.md": "| `prelayout` | schematic netlist | ... |\n",
        "signoff/prelayout/REPORT.md": "x",
        "signoff/postlayout-em/REPORT.md": "x",
    })
    mod, L = _lint_on(root)
    mod.signoff_index(L)
    assert len(L.fails) == 1 and "postlayout-em" in str(L.fails[0])


def test_signoff_index_is_a_noop_before_anything_is_signed_off(tmp_path):
    mod, L = _lint_on(_staged_repo(tmp_path, {"doc/target-spec.md": "x"}))
    mod.signoff_index(L)
    assert L.fails == []


def test_lint_extras_are_green_on_the_bare_template():
    from spicexplorer_harness import load
    from spicexplorer_harness.lint import Lint

    mod = _load("scripts/lint.py")
    L = Lint(load(Path(__file__).resolve().parents[1]))
    for check in mod.EXTRA:
        check(L)
    assert L.fails == []


def _drc_types():
    """The platform's own result types when they are installed, else a field-exact mirror.

    The mirror keeps `count`, which is the whole point: a `DrcViolation` is ALREADY one row per
    rule, so a serializer that counts objects reports `{rule: 1}` beside `n_violations: 20`.
    """
    try:
        from spicexplorer_signoff.results import DrcResult, DrcViolation
    except ImportError:
        from dataclasses import asdict, dataclass, field

        @dataclass
        class DrcViolation:  # mirrors spicexplorer_signoff.results.DrcViolation exactly
            rule: str
            count: int
            locations: list = field(default_factory=list)

        @dataclass
        class DrcResult:
            passed: bool
            available: bool
            n_violations: int = 0
            violations: list = field(default_factory=list)
            report_path: str | None = None
            log: str = ""
            reason: str = ""

            def to_dict(self):
                return asdict(self)

    return DrcResult, DrcViolation


def test_drc_violation_counts_sum_the_aggregated_rows():
    DrcResult, DrcViolation = _drc_types()
    viol = [DrcViolation(rule="M1.a", count=17), DrcViolation(rule="M2.b", count=3)]
    r = DrcResult(passed=False, available=True, n_violations=sum(v.count for v in viol),
                  violations=viol)
    signoff = _load("layout/signoff.py")
    counts = signoff.violation_counts(r.violations)
    assert counts == {"M1.a": 17, "M2.b": 3}
    assert sum(counts.values()) == r.n_violations == 20   # the record must not read as near-clean
    assert json.loads(json.dumps(counts)) == counts
    assert signoff.violation_counts([{"rule": "V1.a", "count": 2}, object()]) == {"V1.a": 2, "?": 1}
    assert signoff.violation_counts([]) == {} and signoff.violation_counts(None) == {}


def test_stage_records_come_from_the_runners_own_to_dict():
    """`_record` keeps every field the platform returns (minus the raw log) — no hand-retyping."""
    DrcResult, DrcViolation = _drc_types()
    signoff = _load("layout/signoff.py")
    r = DrcResult(passed=False, available=True, n_violations=5,
                  violations=[DrcViolation(rule="M1.a", count=5)],
                  report_path="drc.lyrdb", log="x" * 9000, reason="")
    rec = signoff._record(r, pdk="p", density=False)
    assert rec["report_path"] == "drc.lyrdb" and rec["n_violations"] == 5
    assert "log" not in rec and rec["pdk"] == "p"
    assert json.loads(json.dumps(rec, default=str))["violations"][0]["rule"] == "M1.a"


@pytest.fixture
def fake_lanes(monkeypatch):
    """Stand-ins for the physical lanes (absent from this venv), each recording its kwargs."""
    import sys
    import types
    from dataclasses import asdict, dataclass, field

    seen: dict[str, dict] = {}

    @dataclass
    class R:
        ok: bool = True
        passed: bool = True
        available: bool = True
        matched: bool = True
        n_violations: int = 0
        n_checked: int = 0
        n_c: int = 0
        n_r: int = 0
        worst_over_factor: float = 0.0
        mode: str = "CC"
        violations: list = field(default_factory=list)
        unmatched: dict = field(default_factory=dict)
        per_net_c_ff: dict = field(default_factory=dict)
        report_path: str = ""
        netlist_path: str = ""
        log: str = ""
        reason: str = ""

        def to_dict(self):
            return asdict(self)

    class GdsBuilder:
        def __init__(self, gen, out, **kw):
            seen["GdsBuilder"] = kw
            self.last = types.SimpleNamespace(area_um2=1.0, sha="s")

        def __call__(self, params):
            return Path("cell.gds")

    def rec(name):
        def fn(*a, **kw):
            seen[name] = kw
            return R()
        return fn

    layout = types.ModuleType("spicexplorer_layout")
    layout.GdsBuilder, layout.render_png = GdsBuilder, rec("render_png")
    so = types.ModuleType("spicexplorer_signoff")
    so.check_current_density = rec("check_current_density")
    mods = {"spicexplorer_layout": layout, "spicexplorer_signoff": so}
    for sub, fname in (("drc", "run_drc"), ("lvs", "run_lvs"), ("pex", "run_pex")):
        m = types.ModuleType(f"spicexplorer_signoff.{sub}")
        setattr(m, fname, rec(fname))
        mods[f"spicexplorer_signoff.{sub}"] = m
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return seen


def test_build_runs_the_generator_in_the_resolved_interpreter(fake_lanes, monkeypatch, tmp_path):
    """`GdsBuilder(python=None)` falls back to `sys.executable` — this venv, which has no
    gdsfactory. The one function whose purpose is "no default" must actually return its path."""
    signoff = _load("layout/signoff.py")
    monkeypatch.setenv(signoff.GDS_PYTHON_ENV, sys.executable)
    signoff.build(tmp_path)
    assert fake_lanes["GdsBuilder"]["python"] == sys.executable


def test_every_signoff_stage_names_its_pdk(fake_lanes, monkeypatch, tmp_path):
    """No stage may inherit a runner's own default process: a wrong-but-known PDK passes the rule
    deck and the electromigration limits of a technology this design is not built in."""
    signoff = _load("layout/signoff.py")
    monkeypatch.setenv(signoff.PDK_ENV, "some-pdk")
    signoff.render(tmp_path / "c.gds", tmp_path / "c.png")
    signoff.drc(tmp_path / "c.gds", tmp_path / "drc")
    signoff.current_density(tmp_path)
    signoff.lvs(tmp_path / "c.gds", tmp_path / "c.spice", tmp_path / "lvs")
    signoff.pex(tmp_path / "c.gds", tmp_path / "c.spice", tmp_path / "pex")
    for stage in ("render_png", "run_drc", "check_current_density", "run_lvs", "run_pex"):
        assert fake_lanes[stage].get("pdk") == "some-pdk", stage


def test_pdk_has_no_silent_default(monkeypatch):
    signoff = _load("layout/signoff.py")
    monkeypatch.delenv(signoff.PDK_ENV, raising=False)
    assert signoff.PDK.startswith("<")            # the template ships a placeholder, not a process
    with pytest.raises(SystemExit) as e:
        signoff.pdk()
    assert signoff.PDK_ENV in str(e.value) and "FIX:" in str(e.value)


def test_prefix_comes_from_exp_env_not_sim_env():
    """The platform derives every env name from `exp_env` (`Harness.__post_init__`); `sim_env` may
    be set explicitly to something unrelated, and then every var this file asks for is wrong."""
    signoff = _load("layout/signoff.py")
    h = types.SimpleNamespace(exp_env="LDO_EXP", sim_env="NGSPICE_BIN")
    assert signoff._prefix(h) == "LDO"
    assert signoff._prefix(types.SimpleNamespace(exp_env="EXP", sim_env="X_Y")) == "SIM"
    assert signoff.PREFIX == signoff._prefix(signoff.H)


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
    import dataclasses

    h = load(tmp_path)
    lc = dataclasses.replace(metrics.L, h=h, score=_scored({"gain_db": 61.0}))
    lc.certify(_D(), tag="ref", out=tmp_path / "decks" / "reference",
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
