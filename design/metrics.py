"""Fast scorecard: build every bench deck, simulate, promote the measures onto spec keys, check
the box, log the row. Plus the three lifecycle commands both instantiations had to write by hand:
`--certify` (freeze a reference), `--check` (has it drifted? the second half of `make check`) and
`--baseline` (simulate the frozen decks and print the scorecard).

Fill `KEYMAP`: the benches print whatever their template calls a measure, the spec speaks in
unit-scaled keys, and that mapping is the only design-specific thing in this file. Document it
in `doc/benches.md` — a reader must be able to follow one number from the deck to the box.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from spicexplorer_harness import batch, hashes, log_run, provenance, tolerance_band, violations

from . import sim
from .dut import REFERENCE, Design
from .sim import H

# (bench, printed measure) -> (spec/report key, scale). Anything unlisted is kept raw under
# "<bench>.<measure>": visible in the record, never promoted to a scorecard column.
KEYMAP: dict[tuple[str, str], tuple[str, float]] = {}

# Scorecard columns, in report order: the spec keys, then the report-only ones.
COLS: tuple[str, ...] = tuple(r.key for r in H.spec)

# The scorer `provenance()` hashes, DERIVED from this file: a literal would name `design/` still
# after the instantiation rename and every signed `--certify` would die on `sha256_file`.
SCRIPT = Path(__file__).resolve().relative_to(H.root).as_posix()
# A reference column with no `tolerance:` row in harness.yaml drifts at this much, relative to
# its certified value. ngspice is deterministic for a fixed binary + models, so a drift is a
# moved simulator / PDK / deck, never run-to-run spread.
DEFAULT_RTOL = 0.01


class CertifyRefused(RuntimeError):
    """`--certify` ran a bench that did not simulate. Nothing is written; the message is the fix."""


def promote(bench: str, measures: dict) -> dict:
    """Printed measures of one bench -> scorecard keys (`KEYMAP`), scaled."""
    out = {}
    for meas, val in measures.items():
        key, scale = KEYMAP.get((bench, meas), (f"{bench}.{meas}", 1.0))
        out[key] = val * scale if isinstance(val, (int, float)) and not isinstance(val, bool) else val
    return out


def measure(deck: str, tag: str) -> dict:
    """One deck: its own `print`/`meas` scalars (failed measures as NaN).

    A design whose decks write waves instead measures them off `sim.dataset(run)` with the
    platform registry (`spicexplorer_waveview.measure.measure_dataset`) or `sim.raw(run)`.
    """
    r = sim.run(deck, tag)
    return {**r.measures, **{k: float("nan") for k in r.failed}}


def run_decks(decks: dict[str, str], tag: str, *, record: bool = True) -> tuple[dict, dict]:
    """Simulate `{bench: deck}` in parallel; return (scorecard values, per-bench records).

    A bench that fails is a record with `status: sim_error`, not an exception: the other benches
    still produce their columns and the scorecard says which ones are missing.
    """

    def one(bench: str) -> tuple[str, dict]:
        t0 = time.perf_counter()
        rec: dict = {"bench": bench, "deck": decks[bench]}
        try:
            r = sim.run(decks[bench], f"{tag}__{bench}")
            rec.update(status="ok", measures=r.measures, failed=list(r.failed), wall=r.wall)
        except sim.SimError as exc:
            rec.update(status="sim_error", error=str(exc)[:800], measures={}, failed=[],
                       wall=time.perf_counter() - t0)
        return bench, rec

    records = dict(batch(list(decks), one, env=H.jobs_env, on_error="raise"))
    values: dict = {}
    for bench, rec in records.items():
        if rec["status"] == "ok":
            values.update(promote(bench, rec["measures"]))
            values.update(promote(bench, {m: float("nan") for m in rec["failed"]}))
        if record:
            log_run(H, f"{tag}__{bench}", {"bench": bench, "status": rec["status"]},
                    kind="bench", deck=rec["deck"], wall=rec["wall"])
    return values, records


def evaluate(design: Design, tag: str, *, record: bool = True, benches=None) -> dict:
    """One sizing point through every declared bench; one `evaluate` row plus one `bench` row each."""
    benches = list(benches or design.benches())
    decks = {b: design.deck(b) for b in benches}
    t0 = time.perf_counter()
    values, records = run_decks(decks, tag, record=record)
    viol = violations(H.spec, values)
    row = dict(values)
    if record:
        row = log_run(H, tag, values, deck="".join(decks[b] for b in benches),
                      wall=time.perf_counter() - t0, violations=viol, design=design.as_dict(),
                      extra={"benches": {b: r["status"] for b, r in records.items()}})
    row["_records"] = records
    row["_violations"] = viol
    return row


# ------------------------------------------------------------------ the reference -----

def frozen_dir() -> Path:
    """Where `--certify` writes and `--baseline` reads: the dir holding `reference_scorecard`."""
    if not H.reference_scorecard:
        raise SystemExit("harness.yaml `reference_scorecard:` is empty — name the scorecard first, "
                         "e.g. `reference_scorecard: decks/reference/scorecard.json`")
    return H.path(H.reference_scorecard).parent


def frozen_decks() -> dict[str, str]:
    """The frozen benches EXACTLY as certified (bytes, not a rebuild)."""
    return {p.stem: p.read_text() for p in sorted(frozen_dir().glob("*.spice"))}


def certified_card() -> dict:
    """The certified scorecard document. (Not `certified()` — that name is the harness's own, for
    the spec rows carrying `certify: true`, and one module importing both must not blur them.)"""
    return json.loads(H.path(H.reference_scorecard).read_text())


def certify(design: Design = REFERENCE, tag: str = "reference_certify", out: Path | None = None,
            *, author: str = "", verified_by: str = "", force: bool = False) -> dict:
    """Write `<out>/{<bench>.spice, design.json, decks.sha256, scorecard.json}`; `make freeze` after.

    Sign-off is the SECOND actor's re-run: pass `author=` and `verified_by=` (a `verifiers:` id)
    and the scorecard gains a top-level `tag`/`corner` plus the `provenance:` block that the
    `scorecard-recompute` lint matches against the signed ledger row it writes at the same time.
    Without both names nothing is signed and NO provenance block is written — a block with no
    signed row behind it is a lint failure that no reader can ever green (the trap the LDO
    instance hit: `doc/journal/…/a-signed-row-that-can-never-match.md`).

    Nothing is written unless every bench simulated: `CertifyRefused` otherwise (`--force` to
    certify a deliberately partial reference).
    """
    out = frozen_dir() if out is None else Path(out)
    decks = {b: design.deck(b) for b in design.benches()}
    # Simulate BEFORE anything is written: a half-written frozen dir is one `make freeze` away
    # from a sha-locked reference missing a bench, and `drift()` iterates the CERTIFIED keys, so
    # the missing column can never be noticed again.
    values, records = run_decks(decks, tag)
    bad = sorted(b for b, r in records.items() if r["status"] != "ok")
    if bad and not force:
        raise CertifyRefused(
            f"benches did not run: {bad} — nothing was written to {out}.\n"
            "    FIX: fix the bench (`make doctor`, then run it alone) and re-certify. A frozen "
            "reference missing a bench's columns silently drops them from every later drift check; "
            "pass force=True (CLI `--force`) only to certify a deliberately partial reference")
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.spice"):
        old.unlink()
    for b, text in decks.items():
        (out / f"{b}.spice").write_text(text)
    viol = violations(H.spec, values)
    card = {k: v for k, v in values.items() if isinstance(v, float) and not math.isnan(v)}
    (out / "design.json").write_text(json.dumps(design.as_dict(), indent=1) + "\n")
    # What `provenance(raw=…)` hashes: the deck bytes, digested. Never SHA256SUMS — `make freeze`
    # writes that over the whole dir INCLUDING scorecard.json, so it could never re-derive.
    digest = out / "decks.sha256"
    digest.write_text("".join(f"{hashes.sha256_text(t)}  {b}.spice\n" for b, t in sorted(decks.items())))
    try:
        raw_rel: str | None = digest.relative_to(H.root).as_posix()
    except ValueError:
        # a frozen dir outside the repo (a scratch certification) has NO repo-relative name, and
        # an absolute host path in a committed scorecard leaks a home dir and never re-hashes
        raw_rel = None
    doc: dict = {
        "design": design.as_dict(),
        "scorecard": card,
        "bench_measures": {b: r.get("measures", {}) for b, r in records.items()},
        "bench_status": {b: r["status"] for b, r in records.items()},
        "violations": viol,
    }
    corner = str(getattr(design, "corner", "") or "")
    if author and verified_by:
        prov = provenance(H, tag, card, corner=corner, script=SCRIPT, raw=raw_rel)
        log_run(H, tag, values, corner=corner, deck="".join(decks.values()), violations=viol,
                design=design.as_dict(), author=author, evidence="signed", verified_by=verified_by,
                extra={"benches": {b: r["status"] for b, r in records.items()}},
                **{k: prov[k] for k in hashes.HASH_KEYS})
        doc = {"tag": prov["tag"], "corner": prov["corner"], **doc, "provenance": prov}
    else:
        log_run(H, tag, values, corner=corner, deck="".join(decks.values()), violations=viol,
                design=design.as_dict(),
                extra={"benches": {b: r["status"] for b, r in records.items()}})
    (out / "scorecard.json").write_text(json.dumps(doc, indent=1) + "\n")
    return doc


def drift_limit(key: str, want: float) -> float:
    """How far `key` may move from its certified value: the spec row's `tolerance:` band when it
    declares one, else `DEFAULT_RTOL` of the certified value."""
    for row in H.spec:
        if row.key == key:
            band = tolerance_band(row)
            if band is not None:
                return (band[1] - band[0]) / 2
            break
    return DEFAULT_RTOL * abs(want)


def drift(measured: dict) -> list[tuple[str, float, float, str]]:
    """(key, got, certified, why) per column that moved further than its limit, or is missing."""
    out, ref = [], certified_card().get("scorecard", {})
    for k, want in ref.items():
        if not isinstance(want, (int, float)) or isinstance(want, bool):
            continue
        got = measured.get(k)
        if not isinstance(got, (int, float)) or (isinstance(got, float) and math.isnan(got)):
            out.append((k, float("nan"), float(want), "NOT MEASURED"))
            continue
        limit = drift_limit(k, float(want))
        if abs(float(got) - float(want)) > limit:
            out.append((k, float(got), float(want), f"|delta| {abs(got - want):.4g} > {limit:.4g}"))
    return out


def table(rows: dict[str, dict], cols=COLS) -> str:
    """A markdown findings table. Prose is interpretation; THIS is the finding."""
    out = ["| cell | " + " | ".join(cols) + " | verdict |", "|" + "---|" * (len(cols) + 2)]
    for name, v in rows.items():
        cells = ["-" if not isinstance(v.get(c), (int, float)) or v[c] != v[c] else f"{v[c]:.4g}"
                 for c in cols]
        viol = v.get("_violations", violations(H.spec, v))
        out.append(f"| {name} | " + " | ".join(cells) + f" | {'PASS' if not viol else f'FAIL ({len(viol)})'} |")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="design.metrics")
    ap.add_argument("--certify", action="store_true", help="(re)certify the reference into the frozen dir")
    ap.add_argument("--check", action="store_true", help="exit 1 if the frozen reference drifted")
    ap.add_argument("--baseline", action="store_true", help="simulate the frozen decks, print the scorecard")
    ap.add_argument("--author", default="", help="--certify: who ran it (a signed row needs both names)")
    ap.add_argument("--verified-by", default="", help="--certify: the `verifiers:` id re-measuring it")
    ap.add_argument("--force", action="store_true", help="--certify: write even if a bench failed")
    a = ap.parse_args(argv)
    if a.certify:
        try:
            doc = certify(REFERENCE, author=a.author, verified_by=a.verified_by, force=a.force)
        except CertifyRefused as exc:
            print(f"REFUSED: {exc}")
            return 1
        print(table({"reference (certified)": {**doc["scorecard"], "_violations": doc["violations"]}}))
        print("\nbench status:", doc["bench_status"])
        print("\nnow `make freeze` to sha-lock the frozen dir"
              + ("" if "provenance" in doc else "; re-run with --author/--verified-by to sign it"))
        return 0
    if not H.reference_scorecard or not H.path(H.reference_scorecard).exists():
        print("SKIP: no reference certified yet (harness.yaml `reference_scorecard:` is empty or "
              "missing); `make certify`, `make freeze`, then compare it here")
        return 0
    decks = frozen_decks()
    if not decks:
        print(f"SKIP: no *.spice in {frozen_dir()} — nothing frozen to re-measure")
        return 0
    values, records = run_decks(decks, "reference_check")
    values["_violations"] = violations(H.spec, values)
    log_run(H, "reference_check", {k: v for k, v in values.items() if not k.startswith("_")},
            deck="".join(decks.values()), violations=values["_violations"],
            extra={"benches": {b: r["status"] for b, r in records.items()}})
    print(table({"reference (frozen decks)": values}))
    bad = [b for b, r in records.items() if r["status"] != "ok"]
    if bad:
        print("\nbenches that did not run:", bad)
    if a.check:
        d = drift(values)
        if d or bad:
            print("\nDRIFT against " + H.reference_scorecard + ":")
            for k, got, want, why in d:
                print(f"  {k:16s} got {got:.6g}  certified {want:.6g}  ({why})")
            print("\nFIX: the simulator, the PDK, a bench template or the deck builder moved; "
                  "re-certify deliberately (`make certify && make freeze`) and re-measure every "
                  "A/B that was scored against the old reference")
            return 1
        print("\nreference reproduces its certified scorecard")
    return 0


if __name__ == "__main__":  # `make check` / `make baseline` / `make certify`
    sys.exit(main())
