"""Layout sign-off: GDS -> render -> DRC -> current density -> LVS -> PEX -> the cell's OWN benches.

Every stage is a platform runner (`spicexplorer_layout`, `spicexplorer_signoff`); this file only
sequences them and writes the verdicts a reviewer reads. Imports are lazy so the module loads
(and its serializers stay testable) in a venv that has no physical lanes.

    <PREFIX>_EXP=005 uv run --no-sync python layout/signoff.py --all

**Two lanes, picked by `lane:` in harness.yaml** (the key that picks the simulator lane):

* absent, the open lane: the stages below, on this machine (gdsfactory, KLayout, kpex).
* `bridge`, a commercial kit: `main_bridge`. The generator is `layout/gen_cell_bridge.py`
  (`plan(params, kit) -> LayoutPlan`); `build` writes the SKILL file that builds the cell in the
  design's OA library on the EDA server (and loads it with `--load`, which `--all` and any build
  plus drc/lvs/pex require, as `workflows.layout` does); one batch run there streams
  the cell out and answers DRC, LVS and PEX together (`spicexplorer_signoff.calibre.run_calibre`);
  `benches` re-runs the cell's own benches on the extracted DSPF
  (`spicexplorer_spectre.postlayout.splice_dspf`) through the same `metrics.run_decks`. There is no
  render (the layer colours are kit data) and no `jmax` (the kit file has no electromigration
  table, so the stage is recorded as skipped). Every kit fact comes from the kit file
  `$SX_KIT_FILE` names; `signoff.json` and `scorecard.md` have the same shape on both lanes.

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
import hashlib
import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from spicexplorer_harness import load

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
LANE = str(getattr(H, "lane", "") or "")
OA_LIB_ENV = f"{PREFIX}_OA_LIB"
WORKAREA_ENV = f"{PREFIX}_WORKAREA"
GEN_BRIDGE = Path(__file__).resolve().parent / "gen_cell_bridge.py"
# Bridge lane: the `include` files of the benches that define the schematic subckt of CELL; the
# DSPF defines it after the splice, so each one is dropped from the post-layout decks.
DROP_INCLUDES: list[str] = []


def pdk() -> str:
    """Which process the sign-off stages score against. No silent default, for the same reason
    `gds_python()` has none: a wrong-but-known PDK passes every stage and means nothing."""
    p = os.environ.get(PDK_ENV, "") or ("" if PDK.startswith("<") else PDK)
    if not p:
        raise SystemExit(
            f"no PDK named: set `PDK` in layout/signoff.py (got {PDK!r}) or export {PDK_ENV}=<name>."
            f"\n    FIX: every runner (run_drc/run_lvs/run_pex/render_png/check_current_density) "
            "otherwise falls back to ITS OWN default process — the rule deck and the current-"
            "density limits of a technology this design may not be built in"
        )
    return p


def gds_python() -> str:
    """The interpreter that can import gdsfactory + the PDK cells. No default on purpose."""
    p = os.environ.get(GDS_PYTHON_ENV, "")
    if not p or not Path(p).is_file():
        raise SystemExit(
            f"{GDS_PYTHON_ENV} must name the interpreter that has gdsfactory and the PDK cells "
            f"(got {p!r}).\n    FIX: export {GDS_PYTHON_ENV}=/path/to/that/python — record the "
            "path in doc/environment.md, never hard-code someone's home directory here"
        )
    return p  # NOT `None`: GdsBuilder(python=None) falls back to sys.executable, i.e. THIS venv


# ------------------------------------------------------------------ build / render ----


def build(out: Path, sizing: Path | None = None, params: dict | None = None) -> dict:
    """GDS + the LVS reference netlist, built in the generator's own interpreter."""
    from spicexplorer_layout import GdsBuilder

    out.mkdir(parents=True, exist_ok=True)
    builder = GdsBuilder(
        GEN, out, cell=CELL, sizing_json=str(sizing) if sizing else None, python=gds_python()
    )
    gds = builder(params or {})
    b = builder.last
    return {
        "gds": str(gds),
        "area_um2": getattr(b, "area_um2", None),
        "sha": getattr(b, "sha", ""),
        "params": dict(params or {}),
    }


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
    return _record(
        r, density=bool(density), pdk=pdk(), violations_per_rule=violation_counts(r.violations)
    )


def current_density(out: Path) -> dict:
    """The electromigration budget no rule deck checks — arithmetic over `BUDGETS`, no GDS parsed.

    Fill `BUDGETS` with the few nets that carry real current (supply, ground, output) as the
    layout actually draws them. A budget whose limit cannot be resolved is NOT a pass: silence
    from a check that did not run is not evidence.
    """
    from spicexplorer_signoff import check_current_density

    r = check_current_density(BUDGETS, pdk=pdk())
    if getattr(r, "skipped", False):  # no budget given: not a pass, and not a failure either
        print(f"  Jmax: skipped ({r.reason})")
    else:
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
    return _record(
        r,
        pdk=pdk(),
        top_c_ff={k: round(v, 3) for v, k in top},
        log_tail="" if r.ok else (r.log or "")[-1500:],
    )


def benches(pex_netlist: Path, out: Path, tag: str = "postlayout") -> dict:
    """The post-layout scorecard: the cell's OWN benches with the extracted subckt spliced in.

    Nothing new is measured here — same benches, same `metrics.promote`, so the pre and
    post columns are comparable by construction.
    """
    from spicexplorer_signoff.postlayout import prep_pex_subckt, splice_subckt

    block = prep_pex_subckt(pex_netlist, CELL)
    (out / "extracted_subckt.spice").write_text(block)
    pre_decks = {b: REFERENCE.deck(b) for b in REFERENCE.benches()}
    post_decks = {b: splice_subckt(pre_decks[b], block, CELL, check_pins=False) for b in pre_decks}
    pre, _ = M.run_decks(pre_decks, f"{tag}_pre")
    post, post_rec = M.run_decks(post_decks, f"{tag}_post")
    from spicexplorer_harness import violations as _viol

    rec = {
        "pre": pre,
        "post": post,
        "pre_violations": _viol(H.spec, pre),
        "post_violations": _viol(H.spec, post),
        "bench_status": {b: r["status"] for b, r in sorted(post_rec.items())},
    }
    table = M.table({"pre-layout (schematic)": pre, "post-layout (extracted)": post})
    (out / "scorecard.md").write_text(table + "\n")
    print("\n" + table)
    return rec


# ------------------------------------------------------------------ bridge lane -------


def kit():
    """The kit file `$SX_KIT_FILE` names (`spicexplorer_core.kit`); unset is an error with its fix."""
    from spicexplorer_core.kit import KIT_FILE_ENV, load_kit

    if not os.environ.get(KIT_FILE_ENV, "").strip():
        raise SystemExit(
            f"lane: bridge reads every kit fact from the kit file, and {KIT_FILE_ENV} is unset."
            f"\n    FIX: export {KIT_FILE_ENV}=<the kit YAML in the private repo that owns the "
            "kit> (doc/environment.md, row `kit file`)"
        )
    return load_kit()


def oa_lib(given: str | None = None) -> str:
    """The OA library the cell is built and checked in: `--lib`, else `$<PREFIX>_OA_LIB`."""
    lib = given or os.environ.get(OA_LIB_ENV, "")
    if not lib:
        raise SystemExit(
            f"lane: bridge builds {CELL} in an OA library on the EDA server, and none is named."
            f"\n    FIX: pass --lib <library> or export {OA_LIB_ENV}=<library> (doc/environment.md,"
            " row `OA library`); name it for the design, never for a tool"
        )
    return lib


def _generator_plan(gen: Path):
    """`plan(params, kit)` of the bridge-lane generator module at `gen`."""
    spec = importlib.util.spec_from_file_location(f"_{gen.stem}_bridge_generator", gen)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load the generator {gen}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # a dataclass in the generator looks its module up here
    spec.loader.exec_module(mod)
    fn = getattr(mod, "plan", None)
    if not callable(fn):
        raise SystemExit(f"{gen.name} defines no plan(params, kit): see layout/gen_cell_bridge.py")
    return fn


def build_bridge(
    out: Path,
    lib: str,
    params: dict | None = None,
    *,
    gen: Path | None = None,
    load: bool = False,
    client=None,
) -> dict:
    """The generator's `LayoutPlan` -> the SKILL file that builds the cell in `lib`.

    With `load`, the file is loaded into the running editor session through the bridge, which
    creates the cell's `layout` view in `lib`; the SKILL is written with the platform's default
    `overwrite=False`, so it stops with an error when that view already exists (delete it first
    to rebuild). Without `load`, nothing leaves this machine.
    """
    from spicexplorer_layout.backends.virtuoso import load_layout, write_skill

    k = kit()
    plan = _generator_plan(gen or GEN_BRIDGE)(dict(params or {}), k)
    if plan.cell != CELL:
        raise SystemExit(f"the generator builds cell {plan.cell!r}, this file signs off {CELL!r}")
    il = write_skill(plan, k, out / "skill" / f"{plan.cell}_layout.il", lib=lib)
    rec = {
        "skill": str(il),
        "cell": plan.cell,
        "lib": lib,
        "kit": k.info.name,
        "params": dict(params or {}),
        "instances": len(plan.instances),
        "loaded": False,
    }
    if load:
        outcome = load_layout(il, client=client)
        rec.update(loaded=outcome.ok, load_error=outcome.error or "")
        if not outcome.ok:
            raise SystemExit(f"loading {il.name} into the editor failed: {outcome.error}")
    print(f"  SKILL: {il.name} instances={rec['instances']} loaded={rec['loaded']}")
    return rec


def checks_bridge(
    out: Path, lib: str, checks: tuple[str, ...], *, workarea: str | None = None, runner=None
):
    """One batch run on the EDA server for every check in `checks` (`drc`, `lvs`, `pex`).

    The layout is streamed out of `lib` and the schematic view there is the LVS and PEX source,
    so no local GDS or netlist is an input. `runner` is the remote runner (None: this account's
    bridge profile); the run directory and its `run_meta.json` are under `out/calibre/`.
    """
    from spicexplorer_signoff.calibre import CalibreJob, run_calibre

    job = CalibreJob(cell=CELL, lib=lib, checks=checks, workarea=workarea)
    run = run_calibre(kit(), job, work_root=out / "calibre", runner=runner)
    print(f"  checks {','.join(checks)}: status={run.status} {run.reason}".rstrip())
    return run


def drc_bridge(run) -> dict:
    """DRC from the batch run. `passed` counts the non-density results only; the density results
    are reported beside them (`n_density_violations`) and are met by fill, never waived by hand."""
    r = run.drc
    if r is None:
        return {"passed": False, "available": False, "reason": run.reason or "DRC did not run"}
    n_density = int(getattr(r, "n_density_violations", 0) or 0)
    print(f"  DRC: passed={r.passed} violations={r.n_violations} density={n_density}")
    return _record(r, lane="bridge", violations_per_rule=violation_counts(r.violations))


def lvs_bridge(run) -> dict:
    r = run.lvs
    if r is None:
        return {"matched": False, "available": False, "reason": run.reason or "LVS did not run"}
    rec = _record(r, lane="bridge", matched=bool(r.matched))
    if not r.matched and not (r.reason or "").strip():
        rec["log_tail"] = (r.log or "")[-1500:]
    print(f"  LVS: matched={bool(r.matched)}")
    return rec


def pex_bridge(run) -> dict:
    """PEX from the batch run: the DSPF path and its port order, which `benches_bridge` needs."""
    r = run.pex
    if r is None:
        return {"ok": False, "available": False, "reason": run.reason or "PEX did not run"}
    top = sorted(((v, k) for k, v in (r.per_net_c_ff or {}).items()), reverse=True)[:12]
    print(f"  PEX: ok={r.ok} n_C={r.n_c} n_R={r.n_r} ports={len(r.port_order or [])}")
    return _record(
        r,
        lane="bridge",
        top_c_ff={k: round(v, 3) for v, k in top},
        log_tail="" if r.ok else (r.log or "")[-1500:],
    )


def benches_bridge(dspf: Path, port_order: list[str], out: Path, tag: str = "postlayout") -> dict:
    """The post-layout scorecard on the bridge lane: the cell's OWN benches on its DSPF.

    `splice_dspf` rewires every instance of CELL into the DSPF's port order and inserts the
    `dspf_include` line; the DSPF itself is staged beside each deck (the lane uploads by
    basename). Same benches, same `metrics.run_decks`, so the two columns compare.

    The staged copy is named for its content (`<cell>.<sha256[:12]>.dspf`). The lane keys a run
    directory on the deck text alone and re-attaches to a run of the same deck, so a DSPF staged
    under one fixed name would let a re-extracted layout reuse the previous extraction's run.
    """
    from spicexplorer_spectre.postlayout import splice_dspf

    text = dspf.read_text(errors="replace")
    staged_name = f"{CELL}.{hashlib.sha256(text.encode()).hexdigest()[:12]}.dspf"
    pre_decks = {b: REFERENCE.deck(b) for b in REFERENCE.benches()}
    post_decks: dict[str, str] = {}
    rewired: dict[str, int] = {}
    for b, deck in pre_decks.items():
        sp = splice_dspf(
            deck,
            dspf,
            port_order,
            cell=CELL,
            drop_includes=DROP_INCLUDES,
            include_as=staged_name,
        )
        post_decks[b], rewired[b] = sp.deck, len(sp.instances)
    staged = {"extra_files": {staged_name: text}}
    pre, _ = M.run_decks(pre_decks, f"{tag}_pre")
    post, post_rec = M.run_decks(post_decks, f"{tag}_post", run_kwargs=staged)
    from spicexplorer_harness import violations as _viol

    rec = {
        "pre": pre,
        "post": post,
        "pre_violations": _viol(H.spec, pre),
        "post_violations": _viol(H.spec, post),
        "bench_status": {b: r["status"] for b, r in sorted(post_rec.items())},
        "rewired_instances": rewired,
        "dspf": staged_name,
    }
    table = M.table({"pre-layout (schematic)": pre, "post-layout (extracted)": post})
    (out / "scorecard.md").write_text(table + "\n")
    print("\n" + table)
    return rec


STAGES_BRIDGE = ("build", "drc", "jmax", "lvs", "pex", "benches")
CHECK_STAGES = ("drc", "lvs", "pex")


def main_bridge(a: argparse.Namespace, out: Path, stages: tuple[str, ...], *, runner=None) -> dict:
    """The bridge lane's stages (`lane: bridge`); returns the `signoff.json` record.

    A build together with DRC/LVS/PEX is refused without `--load`, before any stage runs: the
    checks stream the layout view already in the OA library, not the SKILL this build writes.
    `workflows.layout` applies the same rule, so `make layout-flow` and this file agree.
    """
    unloaded = sorted(c for c in CHECK_STAGES if c in stages)
    if "build" in stages and unloaded and not a.load:
        raise SystemExit(
            f"{unloaded} would check the layout view already in the OA library, not the SKILL "
            "this build writes (no --load).\n    FIX: pass --load to load it, or run the build "
            "alone (--stages build) and the checks alone (--stages drc,lvs,pex) on the view "
            "in the library"
        )
    lib = oa_lib(a.lib)
    workarea = a.workarea or os.environ.get(WORKAREA_ENV) or None
    params = json.loads(a.params) if a.params else {}
    if a.sizing:
        params.setdefault("sizing", a.sizing)
    rec: dict = {"lane": "bridge"}
    if "build" in stages:
        print("build:")
        rec["build"] = build_bridge(out, lib, params, load=a.load)
    checks = tuple(c for c in CHECK_STAGES if c in stages)
    if checks:
        run = checks_bridge(out, lib, checks, workarea=workarea, runner=runner)
        rec["calibre_run"] = {"dir": str(run.dir), "status": run.status, "reason": run.reason}
        if "drc" in checks:
            print("drc:")
            rec["drc"] = drc_bridge(run)
        if "lvs" in checks:
            print("lvs:")
            rec["lvs"] = lvs_bridge(run)
        if "pex" in checks:
            print("pex:")
            rec["pex"] = pex_bridge(run)
    if "jmax" in stages:
        reason = "the kit file carries no electromigration table, so no budget can be scored"
        print(f"  Jmax: skipped ({reason})")
        rec["current_density"] = {"skipped": True, "passed": False, "reason": reason}
    if "benches" in stages:
        pex = rec.get("pex") or _previous(out).get("pex") or {}
        dspf, ports = pex.get("netlist_path"), list(pex.get("port_order") or [])
        if not dspf or not Path(dspf).is_file() or not ports:
            raise SystemExit(
                f"no DSPF with a port order under {out}: run the pex stage first (this run or "
                "an earlier one into the same --out)"
            )
        print("benches:")
        rec["benches"] = benches_bridge(Path(dspf), ports, out)
    return rec


def _previous(out: Path) -> dict:
    """The `signoff.json` an earlier run wrote into `out`, or {}."""
    try:
        return json.loads((out / "signoff.json").read_text())
    except (OSError, ValueError):
        return {}


#: the platform's "this account cannot reach the EDA server" errors: (module, class)
NOT_CONFIGURED = (
    ("spicexplorer_signoff.calibre", "CalibreNotConfigured"),
    ("spicexplorer_spectre.lane", "LaneNotConfigured"),
)
NOT_CONFIGURED_FIX = (
    "FIX: give this account a bridge profile: run the bridge's own `init` command from the bridge"
    " venv, or ask the admin for one (doc/environment.md, row `bridge profile`)"
)


def _not_configured() -> tuple[type[BaseException], ...]:
    """The classes of `NOT_CONFIGURED` this venv has; an absent package contributes none."""
    found: list[type[BaseException]] = []
    for module, name in NOT_CONFIGURED:
        try:
            cls = getattr(importlib.import_module(module), name, None)
        except ImportError:
            continue
        if isinstance(cls, type) and issubclass(cls, BaseException):
            found.append(cls)
    return tuple(found)


# ------------------------------------------------------------------ driver ------------

STAGES = ("build", "render", "drc", "jmax", "lvs", "pex", "benches")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=f"{CELL} layout sign-off")
    ap.add_argument("--out", default=str(work() / "layout"))
    ap.add_argument("--stages", default="", help="comma list (default: every stage of the lane)")
    ap.add_argument("--all", action="store_true", help="every stage (the default set)")
    ap.add_argument("--density", action="store_true", help="include the DRC density/fill tables")
    ap.add_argument("--sizing", default=None, help="design.json the generator reads sizes from")
    ap.add_argument("--params", default=None, help="bridge lane: generator params as JSON")
    ap.add_argument("--lib", default=None, help=f"bridge lane: the OA library (or ${OA_LIB_ENV})")
    ap.add_argument("--workarea", default=None, help=f"bridge lane: the workarea (${WORKAREA_ENV})")
    ap.add_argument(
        "--load",
        action="store_true",
        help="bridge lane: load the SKILL into the running editor (creates the layout view); "
        "required when build runs with drc/lvs/pex",
    )
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lane_stages = STAGES_BRIDGE if LANE == "bridge" else STAGES
    stages = lane_stages if a.all or not a.stages else tuple(s for s in a.stages.split(",") if s)
    unknown = sorted(set(stages) - set(lane_stages))
    if unknown:
        raise SystemExit(f"unknown stage(s) {unknown} on lane {LANE or 'open'}: {lane_stages}")
    if LANE == "bridge":
        try:
            rec = main_bridge(a, out, stages)
        except Exception as exc:  # re-raised below unless it is a not-configured class
            if not isinstance(exc, _not_configured()):
                raise
            print(f"layout/signoff.py: {exc}\n    {NOT_CONFIGURED_FIX}", file=sys.stderr)
            return 2
        (out / "signoff.json").write_text(json.dumps(rec, indent=1, default=str) + "\n")
        print("\nwrote", out / "signoff.json")
        return 0
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
