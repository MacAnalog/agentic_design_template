"""`scripts/clean_runs.py`: which raw records may go, which may not, and what the doctor says.

template#37 — 212 GB of already-reduced transient records in one account's scratch, because
nothing in the flow owned deletion. What is tested here is the SELECTION, which is pure: a run
directory is removed only when a ledger row says its reduction happened, nothing is writing into
it, and its simulator log has gone cold. Everything else is printed with the reason it survived.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import clean_runs as cr  # noqa: E402

HOUR = 3600.0


def _load_lint():
    spec = importlib.util.spec_from_file_location("lint_for_scratch", REPO / "scripts" / "lint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_dir(runs: Path, name: str, *, log: str = "ngspice.out", age_h: float = 48.0,
             size: int = 1024, busy: bool = False) -> Path:
    """One plausible run directory: a deck, a rawfile, and a simulator log of a chosen age."""
    d = runs / name
    d.mkdir(parents=True)
    (d / "deck.sp").write_text("* deck\n")
    (d / "sim.raw").write_bytes(b"0" * size)
    if busy:
        (d / cr.BUSY).write_text("1 host")
    if log:
        p = d / log
        p.write_text("simulator log\n")
        old = time.time() - age_h * HOUR
        os.utime(p, (old, old))
    return d


# ------------------------------------------------------------------ pure ---------------

def test_label_of_strips_only_the_run_hash():
    assert cr.label_of("ac__gain-1a2b3c4d") == "ac__gain"
    assert cr.label_of("sweep_tt-deadbeef") == "sweep_tt"
    assert cr.label_of("ac-gain") == "ac-gain"            # not 8 hex: not a run hash
    assert cr.label_of("ac__gain-1A2B3C4D") == "ac__gain-1A2B3C4D"   # the lanes write lower case


def test_rows_are_grouped_by_the_label_a_directory_name_carries():
    rows = [{"tag": "op check", "status": "ok"}, {"tag": "op_check"}, {"tag": ""}]
    by = cr.rows_by_label(rows)
    assert set(by) == {"op_check"} and len(by["op_check"]) == 2   # `slug` folds the space


def test_reduced_is_a_row_that_is_not_a_bare_sim_error():
    assert not cr.reduced([])
    assert not cr.reduced([{"status": "sim_error"}, {"status": "sim_error"}])
    assert cr.reduced([{"status": "sim_error"}, {"status": "ok"}])
    assert cr.reduced([{"status": "meas_error"}])      # it measured SOMETHING; that is a reduction
    assert cr.reduced([{"tag": "t", "gain_db": 62.4}])  # an evaluate row has no status column


@pytest.mark.parametrize("kw, delete, phrase", [
    (dict(busy=True, age_s=99 * HOUR, rows=[{"status": "ok"}]), False, "in progress"),
    (dict(busy=False, age_s=99 * HOUR, rows=[]), False, "no ledger row"),
    (dict(busy=False, age_s=99 * HOUR, rows=[{"status": "sim_error"}]), False, "the evidence"),
    (dict(busy=False, age_s=None, rows=[{"status": "ok"}]), False, "no simulator log"),
    (dict(busy=False, age_s=2 * HOUR, rows=[{"status": "ok"}]), False, "AGE=24"),
    (dict(busy=False, age_s=99 * HOUR, rows=[{"status": "ok"}]), True, "reduced"),
])
def test_decide_keeps_everything_it_cannot_prove_is_spent(kw, delete, phrase):
    got, why = cr.decide(age_h=24.0, **kw)
    assert got is delete and phrase in why


def test_decide_reports_the_protecting_reason_before_the_age_one():
    """A young unreduced run is kept because nothing reduced it — saying "too young" would tell
    the designer to wait, when what is needed is a reduction."""
    _, why = cr.decide(busy=False, age_s=1 * HOUR, rows=[], age_h=24.0)
    assert "no ledger row" in why


# ------------------------------------------------------------------ sweeping -----------

def test_scan_and_remove_delete_only_the_spent_records(tmp_path):
    runs = tmp_path / "work" / "runs"
    _run_dir(runs, "ac__gain-11111111", age_h=48)                 # reduced + cold  -> goes
    _run_dir(runs, "tran__eye-22222222", age_h=2)                 # still warm      -> kept
    _run_dir(runs, "tran__eye-33333333", age_h=48, busy=True)     # running         -> kept
    _run_dir(runs, "probe-44444444", age_h=99)                    # no ledger row   -> kept
    _run_dir(runs, "dead__op-55555555", age_h=99)                 # only sim_error  -> kept
    _run_dir(runs, "unfinished-66666666", log="", age_h=0)        # no log          -> kept
    rows = [{"tag": "ac__gain", "status": "ok"}, {"tag": "tran__eye", "status": "ok"},
            {"tag": "dead__op", "status": "sim_error"}]

    entries = cr.scan(runs, cr.rows_by_label(rows), age_h=24.0)
    assert [e["name"] for e in entries if e["delete"]] == ["ac__gain-11111111"]
    removed, refused = cr.remove(entries, runs, repo=REPO)
    assert refused == [] and [e["name"] for e in removed] == ["ac__gain-11111111"]
    assert not (runs / "ac__gain-11111111").exists()
    assert len(list(runs.iterdir())) == 5
    assert all(e["bytes"] > 0 for e in entries)


def test_a_dry_run_deletes_nothing(tmp_path):
    runs = tmp_path / "work" / "runs"
    _run_dir(runs, "ac__gain-11111111", age_h=48)
    entries = cr.scan(runs, cr.rows_by_label([{"tag": "ac__gain", "status": "ok"}]), age_h=24.0)
    removed, _refused = cr.remove(entries, runs, dry_run=True, repo=REPO)
    assert [e["name"] for e in removed] == ["ac__gain-11111111"]
    assert (runs / "ac__gain-11111111").is_dir()


def test_age_zero_sweeps_every_reduced_record_once_a_campaign_is_over(tmp_path):
    runs = tmp_path / "work" / "runs"
    _run_dir(runs, "ac__gain-11111111", age_h=0.1)
    entries = cr.scan(runs, cr.rows_by_label([{"tag": "ac__gain", "status": "ok"}]), age_h=0.0)
    assert [e["delete"] for e in entries] == [True]


def test_refuse_protects_the_repo_and_anything_that_is_not_a_run_dir(tmp_path):
    runs = tmp_path / "work" / "runs"
    d = _run_dir(runs, "ac__gain-11111111")
    assert cr.refuse(d, runs, repo=REPO) is None
    assert "not a directory" in cr.refuse(d / "deck.sp", runs, repo=REPO)
    assert "not a run directory" in cr.refuse(runs.parent, runs, repo=REPO)
    assert "inside the repo" in cr.refuse(REPO / "design", REPO / "design", repo=REPO)
    link = runs / "link-77777777"
    link.symlink_to(d)
    assert "symlink" in cr.refuse(link, runs, repo=REPO)


def test_remove_refuses_rather_than_deleting_what_the_rules_spare(tmp_path):
    """The delete flag is the SELECTION's verdict; `refuse` is the safety rule, and it wins."""
    runs = tmp_path / "work" / "runs"
    runs.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    removed, refused = cr.remove([{"path": outside, "name": "elsewhere", "delete": True}], runs,
                                 repo=REPO)
    assert removed == [] and refused and "not a run directory" in refused[0]
    assert outside.is_dir()


# ------------------------------------------------------------------ the report ---------

def test_usage_warns_above_the_threshold_and_the_threshold_is_an_env_var(tmp_path, monkeypatch):
    runs = tmp_path / "work" / "runs"
    _run_dir(runs, "ac__gain-11111111", size=4096)
    monkeypatch.delenv(cr.WARN_GB_ENV, raising=False)
    rep = cr.usage(tmp_path / "work")
    assert rep["runs"] == 1 and rep["bytes"] >= 4096 and rep["warn_gb"] == cr.DEFAULT_WARN_GB
    assert rep["over"] is False
    monkeypatch.setenv(cr.WARN_GB_ENV, "0.000001")          # 1 kB
    rep = cr.usage(tmp_path / "work")
    assert rep["over"] is True
    assert "WARNING" in cr.report(rep) and "clean-runs" in cr.report(rep)


def test_report_is_quiet_before_anything_has_simulated(tmp_path):
    assert "does not exist yet" in cr.report(cr.usage(tmp_path / "never"))
    assert cr.report(cr.usage(None), note="no lane") == "scratch: unknown — no lane"


def test_the_cli_reports_and_sweeps(tmp_path, monkeypatch, capsys):
    work = tmp_path / "work"
    _run_dir(work / "runs", "ac__gain-11111111", age_h=48)
    _run_dir(work / "runs", "tran__eye-22222222", age_h=1)
    monkeypatch.setattr(cr, "work_dir", lambda: (work, ""))
    monkeypatch.setattr(cr.LG, "read", lambda h: [{"tag": "ac__gain", "status": "ok"},
                                                  {"tag": "tran__eye", "status": "ok"}])
    assert cr.main(["--report"]) == 0
    assert "scratch:" in capsys.readouterr().out

    assert cr.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "WOULD DELETE" in out and (work / "runs" / "ac__gain-11111111").is_dir()

    assert cr.main(["--age", "24", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["removed"] == ["ac__gain-11111111"]
    assert [k["name"] for k in rep["kept"]] == ["tran__eye-22222222"]
    assert not (work / "runs" / "ac__gain-11111111").exists()


# ------------------------------------------------------------------ the soft lint ------

def _lint_over_threshold(work, rows, monkeypatch):
    from spicexplorer_harness import load
    from spicexplorer_harness.lint import Lint

    mod = _load_lint()
    monkeypatch.setattr(cr, "work_dir", lambda: (work, ""))
    monkeypatch.setenv(cr.WARN_GB_ENV, "0.000001")          # 1 kB, so the fixture is "over"
    L = Lint(load(REPO))
    L._rows = rows
    mod.scratch_budget(L)
    return L


def test_scratch_budget_warns_and_never_fails(tmp_path, monkeypatch):
    work = tmp_path / "work"
    _run_dir(work / "runs", "big__tran-11111111", size=8192, age_h=48)
    _run_dir(work / "runs", "ac__gain-22222222", size=16, age_h=48)
    L = _lint_over_threshold(work, [{"tag": "ac__gain", "status": "ok"}], monkeypatch)
    assert L.fails == []                                   # NEVER a failure (template#37)
    assert len(L.warns) == 1 and "big__tran-11111111" in L.warns[0]
    assert "no reduction row" in L.warns[0] and "clean-runs" in L.warns[0]


def test_scratch_budget_says_so_when_the_big_records_are_all_reduced(tmp_path, monkeypatch):
    work = tmp_path / "work"
    _run_dir(work / "runs", "big__tran-11111111", size=8192, age_h=48)
    L = _lint_over_threshold(work, [{"tag": "big__tran", "status": "ok"}], monkeypatch)
    assert L.fails == [] and len(L.warns) == 1
    assert "already reduced" in L.warns[0] and "clean-runs" in L.warns[0]


def test_scratch_budget_is_silent_under_the_threshold_and_with_no_work_dir(tmp_path, monkeypatch):
    from spicexplorer_harness import load
    from spicexplorer_harness.lint import Lint

    mod = _load_lint()
    work = tmp_path / "work"
    _run_dir(work / "runs", "big__tran-11111111", size=8192)
    monkeypatch.delenv(cr.WARN_GB_ENV, raising=False)
    monkeypatch.setattr(cr, "work_dir", lambda: (work, ""))
    L = Lint(load(REPO))
    L._rows = []
    mod.scratch_budget(L)
    monkeypatch.setattr(cr, "work_dir", lambda: (tmp_path / "never", ""))
    mod.scratch_budget(L)
    monkeypatch.setattr(cr, "work_dir", lambda: (None, "no lane here"))
    mod.scratch_budget(L)
    assert L.warns == [] and L.fails == []
