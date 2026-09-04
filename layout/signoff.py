"""Layout sign-off driver: GDS -> render -> DRC -> LVS -> PEX -> the cell's OWN frozen benches.

Every stage is a platform runner (`spicexplorer_layout`, `spicexplorer_signoff`); this file only
sequences them and writes the verdicts a reviewer reads. Imports are lazy so the module loads
(and its serializers stay testable) in a venv that has no physical lanes.

    <PREFIX>_EXP=005 uv run --no-sync python layout/signoff.py --all

**Two interpreters, deliberately.** The generator needs gdsfactory + the PDK cells; DRC/LVS/PEX
are KLayout runsets and kpex driven from this venv:

* `$<PREFIX>_GDS_PYTHON` — the interpreter that can `import gdsfactory` and the PDK cells.
  There is no default: an unset variable is an error with its fix, never someone's home path.
* `SIGNOFF_PYTHON`, if set, must name an interpreter that can import BOTH the PDK runset's own
  dependencies AND the layout API. Unset resolves to this checkout's venv, which has them. An
  interpreter missing one of them returns `matched=False` with an EMPTY `reason` while the real
  traceback sits in the returned log — which is why `lvs()` below copies the log tail into the
  record (LDO `doc/journal/…run-lvs-swallows-its-own-traceback.md`).

The three lessons baked into the stage functions:

1. `drc()` counts violations PER RULE. The runner's violation objects are not JSON-serialisable,
   so a `json.dumps` of the raw list only ever runs when the list is non-empty — a clean cell
   hides the crash until the first real violation.
2. `lvs()` keeps the raw evidence beside the wrapper's verdict, and surfaces the log when the
   reason is empty.
3. `benches()` re-scores through the SAME path as the pre-layout row (`lab.metrics.run_decks`).
   A tolerant post-layout runner that skips a bench the pre-layout row measured makes the two
   columns incomparable (LDO review-002 M4/M5).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab import metrics as M  # noqa: E402
from lab.dut import REFERENCE  # noqa: E402
from lab.sim import H, work  # noqa: E402

CELL = "<cell>"
GEN = Path(__file__).resolve().parent / "gen_cell.py"
PREFIX = H.sim_env.rsplit("_", 1)[0]          # harness.yaml prefix rule: EXP -> SIM/<DESIGN>
GDS_PYTHON_ENV = f"{PREFIX}_GDS_PYTHON"


def gds_python() -> str:
    """The interpreter that can import gdsfactory + the PDK cells. No default on purpose."""
    p = os.environ.get(GDS_PYTHON_ENV, "")
    if not p or not Path(p).is_file():
        raise SystemExit(
            f"{GDS_PYTHON_ENV} must name the interpreter that has gdsfactory and the PDK cells "
            f"(got {p!r}).\n    FIX: export {GDS_PYTHON_ENV}=/path/to/that/python — record the "
            "path in doc/environment.md, never hard-code someone's home directory here")


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
        render_png(gds, png)
        return {"ok": png.is_file(), "png": str(png)}
    except Exception as exc:  # noqa: BLE001 — a missing renderer is not a sign-off failure
        return {"ok": False, "png": str(png), "reason": str(exc)[:400]}


# ------------------------------------------------------------------ sign-off ----------

def violation_counts(violations) -> dict[str, int]:
    """Violations -> {rule: count}: JSON-safe whatever the runner's objects are.

    Serialising the raw list crashes on the first REAL violation and never before, because the
    line only runs when the list is non-empty. Which rules fired is also what a reviewer reads.
    """
    per_rule: dict[str, int] = {}
    for v in violations or ():
        rule = str(getattr(v, "rule", None) or (v.get("rule") if isinstance(v, dict) else None) or "?")
        per_rule[rule] = per_rule.get(rule, 0) + 1
    return dict(sorted(per_rule.items(), key=lambda kv: (-kv[1], kv[0])))


def drc(gds: Path, out: Path, *, density: bool = False) -> dict:
    """Rule check. Density/fill tables are off by default: a standalone cell cannot satisfy them
    on its own (they are met by fill at chip assembly). Say so in the README and run `--density`
    at least once, so "0 violations" is not quietly a smaller claim than a reader assumes."""
    from spicexplorer_signoff.drc import run_drc

    r = run_drc(str(gds), CELL, str(out), no_density=not density)
    print(f"  DRC: passed={r.passed} violations={r.n_violations}")
    return {"passed": bool(r.passed), "available": bool(r.available), "density": bool(density),
            "n_violations": int(r.n_violations), "violations_per_rule": violation_counts(r.violations),
            "report": r.report_path, "reason": r.reason}


def lvs(gds: Path, netlist: Path, out: Path) -> dict:
    from spicexplorer_signoff.lvs import run_lvs

    r = run_lvs(str(gds), str(netlist), CELL, str(out))
    log = r.log or ""
    matched = bool(r.matched) or "Netlists match" in log
    rec = {"passed": bool(r.passed), "matched": matched, "available": bool(r.available),
           "unmatched": dict(r.unmatched or {}), "report": r.report_path,
           "netlist_sha": getattr(r, "netlist_sha", ""), "reason": r.reason}
    if not matched and not (r.reason or "").strip():
        # the runner does not promote a non-zero exit into `reason`; the cause is in the log
        rec["log_tail"] = log[-1500:]
    print(f"  LVS: matched={matched}")
    return rec


def pex(gds: Path, netlist: Path, out: Path, *, mode: str = "CC") -> dict:
    from spicexplorer_signoff.pex import run_pex

    r = run_pex(gds, CELL, netlist, out, mode=mode)
    print(f"  PEX: ok={r.ok} n_C={r.n_c} n_R={r.n_r}")
    top = sorted(((v, k) for k, v in (r.per_net_c_ff or {}).items()), reverse=True)[:12]
    return {"ok": bool(r.ok), "available": bool(r.available), "mode": r.mode,
            "netlist": r.netlist_path, "n_c": int(r.n_c), "n_r": int(r.n_r),
            "per_net_c_ff": {k: round(v, 3) for v, k in top}, "reason": r.reason,
            "log_tail": (r.log or "")[-1500:] if not r.ok else ""}


def benches(pex_netlist: Path, out: Path, tag: str = "postlayout") -> dict:
    """The post-layout scorecard: the cell's OWN benches with the extracted subckt spliced in.

    Nothing new is measured here — same benches, same `lab.metrics` promotion, so the pre and
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

STAGES = ("build", "render", "drc", "lvs", "pex", "benches")


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
        print("build:"); rec["build"] = build(out, Path(a.sizing) if a.sizing else None)
    if "render" in stages:
        print("render:"); rec["render"] = render(gds, out / f"{CELL}.png")
    if "drc" in stages:
        print("drc:"); rec["drc"] = drc(gds, out / "drc", density=a.density)
    if "lvs" in stages:
        print("lvs:"); rec["lvs"] = lvs(gds, netlist, out / "lvs")
    if "pex" in stages:
        print("pex:"); rec["pex"] = pex(gds, netlist, out / "pex")
    if "benches" in stages:
        hits = sorted((out / "pex").rglob("*_pex_netlist.spice"))
        if not hits:
            raise SystemExit(f"no kpex netlist under {out / 'pex'} — run the pex stage first")
        print("benches:"); rec["benches"] = benches(hits[-1], out)
    (out / "signoff.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
    print("\nwrote", out / "signoff.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
