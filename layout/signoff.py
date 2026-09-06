"""Layout sign-off: GDS -> render -> DRC -> current density -> LVS -> PEX -> the cell's OWN benches.

Every stage is a platform runner (`spicexplorer_layout`, `spicexplorer_signoff`); this file only
sequences them and writes the verdicts a reviewer reads. Imports are lazy so the module loads
(and its serializers stay testable) in a venv that has no physical lanes.

    <PREFIX>_EXP=005 uv run --no-sync python layout/signoff.py --all

**Two interpreters, deliberately.** The generator needs gdsfactory + the PDK cells; DRC/LVS/PEX
are KLayout runsets and kpex driven from this venv:

* `$<PREFIX>_GDS_PYTHON` — the interpreter that can `import gdsfactory` and the PDK cells.
  There is no default: an unset variable is an error with its fix, never someone's home path.
  `<PREFIX>` is the harness prefix, derived from `exp_env` the way the platform derives it.
* `SIGNOFF_PYTHON`, if set, must name an interpreter that can import BOTH the PDK runset's own
  dependencies AND the layout API. Unset resolves to this checkout's venv, which has them. An
  interpreter missing one of them returns `matched=False` with an EMPTY `reason` while the real
  traceback sits in the returned log — which is why `lvs()` below copies the log tail into the
  record (LDO `doc/journal/…run-lvs-swallows-its-own-traceback.md`).

The five lessons baked into the stage functions:

0. Every stage takes its verdict from the runner's own `to_dict()` (`_record`) and passes `pdk=`
   from one place. Retyping a result by hand drops fields and invents bugs; letting each runner
   default its PDK scores the cell against another process's rules without saying so.
1. `drc()` splits violations PER RULE, summing each object's `count` — a `DrcViolation` is
   already one row per rule, so counting objects reads as a near-clean cell.
2. `lvs()` keeps the raw evidence beside the wrapper's verdict, and surfaces the log when the
   reason is empty.
3. `benches()` re-scores through the SAME path as the pre-layout row (the design package's `metrics.run_decks`).
   A tolerant post-layout runner that skips a bench the pre-layout row measured makes the two
   columns incomparable (LDO review-002 M4/M5).
4. `current_density()` is a stage, not an afterthought. DRC checks geometry, LVS checks nets and
   PEX models resistance: none of them asks whether the metal carrying the load current is wide
   enough. The LDO cell of record passed all three at 12-28x over the Metal1 limit.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from spicexplorer_harness import load  # noqa: E402

H = load(REPO)
# Resolved through `package:`, never spelled `design.…`: this file must survive the instantiation
# rename untouched (`git mv design <name>` + one line in harness.yaml).
M = importlib.import_module(f"{H.package}.metrics")
REFERENCE = importlib.import_module(f"{H.package}.dut").REFERENCE
work = importlib.import_module(f"{H.package}.sim").work

CELL = "<cell>"
GEN = Path(__file__).resolve().parent / "gen_cell.py"

# What each current-carrying net actually carries, on the conductor the generator draws it on.
# e.g. Budget(net="vout", current_a=10e-3, layer="Metal1", width_um=0.8, note="output pin")
BUDGETS: list = []

# The PDK every stage scores against. EVERY platform runner defaults to one particular process,
# so a design built elsewhere would silently be checked against a foreign rule deck AND foreign
# electromigration limits, with no error. Name yours here (or export `$<PREFIX>_PDK`).
PDK = "<pdk>"


def _prefix(h) -> str:
    """The harness env-name prefix — derived from `exp_env`, exactly as the platform derives it
    (`spicexplorer_harness.config.Harness.__post_init__`). NOT from `sim_env`: that key may be
    set explicitly to an unrelated name, and then every var this file asks for is wrong."""
    return h.exp_env[:-4] if h.exp_env.endswith("_EXP") and len(h.exp_env) > 4 else "SIM"


PREFIX = _prefix(H)
GDS_PYTHON_ENV = f"{PREFIX}_GDS_PYTHON"
PDK_ENV = f"{PREFIX}_PDK"


def pdk() -> str:
    """Which process the sign-off stages score against. No silent default, for the same reason
    `gds_python()` has none: a wrong-but-known PDK passes every stage and means nothing."""
    p = os.environ.get(PDK_ENV, "") or ("" if PDK.startswith("<") else PDK)
    if not p:
        raise SystemExit(
            f"no PDK named: set `PDK` in layout/signoff.py (got {PDK!r}) or export {PDK_ENV}=<name>."
            f"\n    FIX: every runner (run_drc/run_lvs/run_pex/render_png/check_current_density) "
            "otherwise falls back to ITS OWN default process — the rule deck and the current-"
            "density limits of a technology this design may not be built in")
    return p


def gds_python() -> str:
    """The interpreter that can import gdsfactory + the PDK cells. No default on purpose."""
    p = os.environ.get(GDS_PYTHON_ENV, "")
    if not p or not Path(p).is_file():
        raise SystemExit(
            f"{GDS_PYTHON_ENV} must name the interpreter that has gdsfactory and the PDK cells "
            f"(got {p!r}).\n    FIX: export {GDS_PYTHON_ENV}=/path/to/that/python — record the "
            "path in doc/environment.md, never hard-code someone's home directory here")
    return p  # NOT `None`: GdsBuilder(python=None) falls back to sys.executable, i.e. THIS venv


# ------------------------------------------------------------------ build / render ----

def build(out: Path, sizing: Path | None = None, params: dict | None = None) -> dict:
    """GDS + the LVS reference netlist, built in the generator's own interpreter."""
    from spicexplorer_layout import GdsBuilder

    out.mkdir(parents=True, exist_ok=True)
    builder = GdsBuilder(GEN, out, cell=CELL, sizing_json=str(sizing) if sizing else None,
                         python=gds_python())
    gds = builder(params or {})
    b = builder.last
    return {"gds": str(gds), "area_um2": getattr(b, "area_um2", None),
            "sha": getattr(b, "sha", ""), "params": dict(params or {})}


def render(gds: Path, png: Path) -> dict:
    from spicexplorer_layout import render_png

    try:
        render_png(gds, png, pdk=pdk())
        return {"ok": png.is_file(), "png": str(png)}
    except Exception as exc:  # noqa: BLE001 — a missing renderer is not a sign-off failure
        return {"ok": False, "png": str(png), "reason": str(exc)[:400]}


# ------------------------------------------------------------------ sign-off ----------

def violation_counts(violations) -> dict[str, int]:
    """Violations -> {rule: how many}, the per-rule split a reviewer reads.

    A `DrcViolation` is ALREADY AGGREGATED — one object per rule, carrying `count` — and
    `run_drc` reports `n_violations = sum(count)`. Counting the objects instead would print
    `{rule: 1}` beside `n_violations: 20` and read as a near-clean cell.
    """
    per_rule: dict[str, int] = {}
    for v in violations or ():
        d = v if isinstance(v, dict) else getattr(v, "__dict__", {})
        rule = str(d.get("rule") or "?")
        per_rule[rule] = per_rule.get(rule, 0) + int(d.get("count", 1) or 1)
    return dict(sorted(per_rule.items(), key=lambda kv: (-kv[1], kv[0])))


def _record(r, **extra) -> dict:
    """A runner's own `to_dict()` (JSON-clean) plus only what this file genuinely adds.

    Never re-typed field by field: retyping is what let the violation-count bug in, and it
    silently drops whatever the platform adds later (`pdk`, `locations`, `coupling_ff`).
    `log` is replaced by the tails the stages ask for — a full tool log is not a verdict.
    """
    d = {k: v for k, v in r.to_dict().items() if k != "log"}
    d.update(extra)
    return d


def drc(gds: Path, out: Path, *, density: bool = False) -> dict:
    """Rule check. Density/fill tables are off by default: a standalone cell cannot satisfy them
    on its own (they are met by fill at chip assembly). Say so in the README and run `--density`
    at least once, so "0 violations" is not quietly a smaller claim than a reader assumes."""
    from spicexplorer_signoff.drc import run_drc

    r = run_drc(str(gds), CELL, str(out), no_density=not density, pdk=pdk())
    print(f"  DRC: passed={r.passed} violations={r.n_violations}")
    return _record(r, density=bool(density), pdk=pdk(),
                   violations_per_rule=violation_counts(r.violations))


def current_density(out: Path) -> dict:
    """The electromigration budget no rule deck checks — arithmetic over `BUDGETS`, no GDS parsed.

    Fill `BUDGETS` with the few nets that carry real current (supply, ground, output) as the
    layout actually draws them. A budget whose limit cannot be resolved is NOT a pass: silence
    from a check that did not run is not evidence.
    """
    from spicexplorer_signoff import check_current_density

    r = check_current_density(BUDGETS, pdk=pdk())
    print(f"  Jmax: passed={r.passed} over={r.worst_over_factor:.2f}x n={r.n_checked}")
    return _record(r)


def lvs(gds: Path, netlist: Path, out: Path) -> dict:
    from spicexplorer_signoff.lvs import run_lvs

    r = run_lvs(str(gds), str(netlist), CELL, str(out), pdk=pdk())
    log = r.log or ""
    matched = bool(r.matched) or "Netlists match" in log
    rec = _record(r, matched=matched, pdk=pdk())
    if not matched and not (r.reason or "").strip():
        # the runner does not promote a non-zero exit into `reason`; the cause is in the log
        rec["log_tail"] = log[-1500:]
    print(f"  LVS: matched={matched}")
    return rec


def pex(gds: Path, netlist: Path, out: Path, *, mode: str = "CC") -> dict:
    from spicexplorer_signoff.pex import run_pex

    r = run_pex(gds, CELL, netlist, out, mode=mode, pdk=pdk())
    print(f"  PEX: ok={r.ok} n_C={r.n_c} n_R={r.n_r}")
    top = sorted(((v, k) for k, v in (r.per_net_c_ff or {}).items()), reverse=True)[:12]
    return _record(r, pdk=pdk(), top_c_ff={k: round(v, 3) for v, k in top},
                   log_tail="" if r.ok else (r.log or "")[-1500:])


def benches(pex_netlist: Path, out: Path, tag: str = "postlayout") -> dict:
    """The post-layout scorecard: the cell's OWN benches with the extracted subckt spliced in.

    Nothing new is measured here — same benches, same `metrics.promote`, so the pre and
    post columns are comparable by construction.
    """
    from spicexplorer_signoff.postlayout import prep_pex_subckt, splice_subckt

    block = prep_pex_subckt(pex_netlist, CELL)
    (out / "extracted_subckt.spice").write_text(block)
    pre_decks = {b: REFERENCE.deck(b) for b in REFERENCE.benches()}
    post_decks = {b: splice_subckt(pre_decks[b], block, CELL, check_pins=False)
                  for b in pre_decks}
    pre, _ = M.run_decks(pre_decks, f"{tag}_pre")
    post, post_rec = M.run_decks(post_decks, f"{tag}_post")
    from spicexplorer_harness import violations as _viol

    rec = {"pre": pre, "post": post, "pre_violations": _viol(H.spec, pre),
           "post_violations": _viol(H.spec, post),
           "bench_status": {b: r["status"] for b, r in sorted(post_rec.items())}}
    table = M.table({"pre-layout (schematic)": pre, "post-layout (extracted)": post})
    (out / "scorecard.md").write_text(table + "\n")
    print("\n" + table)
    return rec


# ------------------------------------------------------------------ driver ------------

STAGES = ("build", "render", "drc", "jmax", "lvs", "pex", "benches")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=f"{CELL} layout sign-off")
    ap.add_argument("--out", default=str(work() / "layout"))
    ap.add_argument("--stages", default=",".join(STAGES))
    ap.add_argument("--all", action="store_true", help="every stage (the default set)")
    ap.add_argument("--density", action="store_true", help="include the DRC density/fill tables")
    ap.add_argument("--sizing", default=None, help="design.json the generator reads sizes from")
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stages = STAGES if a.all else tuple(s for s in a.stages.split(",") if s)
    gds, netlist = out / f"{CELL}.gds", out / f"{CELL}_lvs.spice"
    rec: dict = {}
    if "build" in stages:
        print("build:")
        rec["build"] = build(out, Path(a.sizing) if a.sizing else None)
    if "render" in stages:
        print("render:")
        rec["render"] = render(gds, out / f"{CELL}.png")
    if "drc" in stages:
        print("drc:")
        rec["drc"] = drc(gds, out / "drc", density=a.density)
    if "jmax" in stages:
        print("current density:")
        rec["current_density"] = current_density(out)
    if "lvs" in stages:
        print("lvs:")
        rec["lvs"] = lvs(gds, netlist, out / "lvs")
    if "pex" in stages:
        print("pex:")
        rec["pex"] = pex(gds, netlist, out / "pex")
    if "benches" in stages:
        hits = sorted((out / "pex").rglob("*_pex_netlist.spice"))
        if not hits:
            raise SystemExit(f"no kpex netlist under {out / 'pex'} — run the pex stage first")
        print("benches:")
        rec["benches"] = benches(hits[-1], out)
    (out / "signoff.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    print("\nwrote", out / "signoff.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
