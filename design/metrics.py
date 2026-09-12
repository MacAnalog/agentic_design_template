"""Fast scorecard: build every bench deck, simulate, promote the measures onto spec keys, check
the box, log the row. Plus the three lifecycle commands both instantiations had to write by hand:
`--certify` (freeze a reference), `--check` (has it drifted? the second half of `make check`) and
`--baseline` (simulate the frozen decks and print the scorecard).

Fill `KEYMAP`: the benches print whatever their template calls a measure, the spec speaks in
unit-scaled keys, and that mapping is the only design-specific thing in this file. Document it
in `doc/benches.md` — a reader must be able to follow one number from the deck to the box.

A bench whose answer is post-processing rather than a printed scalar reduces in `design/bench.py`
(`PRODUCES` + `reduce()`), and this module builds `KEYMAP` from it, so the reduction the harness
certifies and the reduction an experiment reports are the same function. **A reduction that lives
only in an `experiments/NNN-*/run.py` cannot be certified** — `--certify` freezes what `run_decks`
produced, so a number computed after that lands in a report and nowhere else.

**The lifecycle itself is NOT here.** `promote`, `evaluate`, `frozen_dir`, `frozen_decks`,
`certified_card`, `certify`, `drift_limit`, `drift`, `table` and `main` are one shared
implementation — `spicexplorer_harness.lifecycle.Lifecycle` — and this module supplies the five
design-specific things it needs (the reference point, how a design becomes deck files, how decks
become scored values, how a `design.json` loads, and `KEYMAP`). They were copied byte for byte
into four design repos before that, and copying them is how AT-01 — a bench that never ran
certifying as passing — came to exist in every copy at once (platform #176). The names below are
re-exported, so every existing caller (`layout/signoff.py`, an experiment, a doc) keeps working.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from spicexplorer_harness import batch, log_run
from spicexplorer_harness.lifecycle import CertifyRefused, Drift, Lifecycle

from . import bench as bench_mod
from . import sim
from .dut import REFERENCE, Design
from .sim import H

# (bench, measure) -> (spec/report key, scale). Anything unlisted is kept raw under
# "<bench>.<measure>": visible in the record, never promoted to a scorecard column.
# The package-level reduction's keys (`design/bench.py` `PRODUCES`) are promoted under their own
# names; add a row here for every PRINTED measure whose name or unit differs from its spec key,
# e.g. `{("op", "i_supply"): ("power_uw", 1e6)}`.
KEYMAP: dict[tuple[str, str], tuple[str, float]] = {**bench_mod.keymap()}

# Scorecard columns, in report order: the spec keys, then the report-only ones.
COLS: tuple[str, ...] = tuple(r.key for r in H.spec)

# The scorer `provenance()` hashes, DERIVED from this file: a literal would name `design/` still
# after the instantiation rename and every signed `--certify` would die on `sha256_file`.
SCRIPT = Path(__file__).resolve().relative_to(H.root).as_posix()
# A reference column with no `tolerance:` row in harness.yaml drifts at this much, relative to
# its certified value. ngspice is deterministic for a fixed binary + models, so a drift is a
# moved simulator / PDK / deck, never run-to-run spread.
DEFAULT_RTOL = 0.01


def measure(deck: str, tag: str, bench: str = "") -> dict:
    """One deck: its own `print`/`meas` scalars, plus what `design.bench.reduce` makes of the run.

    A design whose decks write waves instead of printing their answer reduces them in
    `design/bench.py` — off `sim.dataset(run)` with the platform registry
    (`spicexplorer_waveview.measure.measure_dataset`) or `sim.raw(run)` — and passes `bench=` so
    this call goes through the same reduction the certified reference is built from. The same
    maths written into an experiment instead is invisible to `--certify` and reproduces nowhere.
    """
    r = sim.run(deck, tag)
    return {**r.measures, **bench_mod.reduce(bench, r), **{k: float("nan") for k in r.failed}}


def run_decks(decks: dict[str, str], tag: str, *, record: bool = True) -> tuple[dict, dict]:
    """Simulate `{bench: deck}` in parallel; return (scorecard values, per-bench records).

    A key may be the bench name or the deck's FILE name (`op` or `op.spice`) — the lifecycle hands
    over file names, because those are the bytes it freezes; the bench name is the stem, and it is
    what a record, a ledger row and `KEYMAP` are keyed by.

    A bench that fails is a record, not an exception: the other benches still produce their columns
    and the scorecard says which ones are missing. Three statuses — `ok` (it ran and every measure
    came out), `meas_error` (it ran; at least one `.meas` did not, so its column is NaN) and
    `sim_error` (it did not run). Only `ok` is a bench `certify()` will freeze.
    """

    named = {Path(k).stem: v for k, v in decks.items()}

    def one(bench: str) -> tuple[str, dict]:
        t0 = time.perf_counter()
        rec: dict = {"bench": bench, "deck": named[bench]}
        try:
            r = sim.run(named[bench], f"{tag}__{bench}")
            # the package-level reduction is merged into the record BEFORE anything is promoted,
            # logged or frozen — that is what makes a post-processed number certifiable at all
            failed = list(r.failed)
            # A deck that SIMULATED is not a deck that MEASURED. A failed `.meas` prints no number,
            # so the column becomes NaN, `certify()` keeps only non-NaN floats and `drift()`
            # iterates the CERTIFIED keys: an `ok` here is how a spec column leaves the frozen
            # reference and is never missed again. `meas_error` keeps the numbers that DID come out
            # (below) while refusing to pass as a complete bench.
            rec.update(status="ok" if not failed else "meas_error",
                       measures={**r.measures, **bench_mod.reduce(bench, r)},
                       failed=failed, wall=r.wall)
        except sim.SimError as exc:
            rec.update(status="sim_error", error=str(exc)[:800], measures={}, failed=[],
                       wall=time.perf_counter() - t0)
        return bench, rec

    records = dict(batch(list(named), one, env=H.jobs_env, on_error="raise"))
    values: dict = {}
    for bench, rec in records.items():
        if rec["status"] != "sim_error":                    # a bench that ran: promote what it has
            values.update(promote(bench, rec["measures"]))
            values.update(promote(bench, {m: float("nan") for m in rec["failed"]}))
        if record:
            log_run(H, f"{tag}__{bench}", {"bench": bench, "status": rec["status"]},
                    kind="bench", deck=rec["deck"], wall=rec["wall"])
    return values, records


# ------------------------------------------------------------------ the lifecycle -----
#
# One shared implementation, wired to this design. What arrives from here is only what a
# lifecycle cannot know: the reference point, how a design becomes deck FILES (the same function
# `lint.deck_rebuild` calls, so the writer and the freshness check can never disagree about what
# the frozen bytes are), how those decks become scored values, how a `design.json` loads back, and
# the KEYMAP. Everything else — where the frozen dir is, when a certification must REFUSE, how far
# a column may drift, what the three CLI commands do — is the harness's.

L = Lifecycle(
    h=H,
    reference=REFERENCE,
    deck_files=lambda d: {f"{b}.spice": d.deck(b) for b in d.benches()},
    score=run_decks,
    load_design=lambda p: Design.load(p),
    script=SCRIPT,
    keymap=KEYMAP,
    cols=COLS,
    default_rtol=DEFAULT_RTOL,
)

# The names this module has always exported. Keep them: `layout/signoff.py`, the experiments and
# the docs call them, and a design that instantiated this template before the extraction should
# see no difference at its call sites.
promote = L.promote
evaluate = L.evaluate
frozen_dir = L.frozen_dir
frozen_decks = L.frozen_decks
certified_card = L.certified_card
certify = L.certify
drift_limit = L.drift_limit
drift = L.drift
table = L.table
main = L.main


if __name__ == "__main__":  # `make check` / `make baseline` / `make certify`
    sys.exit(main(prog="design.metrics"))
