"""Fast scorecard: build the deck, simulate, measure, check the box, log the row."""

from __future__ import annotations

import argparse
import sys
import time

from spicexplorer_harness import log_run, violations

from . import sim
from .dut import Design
from .sim import H


def measure(deck: str, tag: str) -> dict:
    """Default: the deck's own `print`/`meas` scalars (failed measures as NaN).

    A design whose decks write waves instead measures them off `sim.dataset(run)` with the
    platform registry (`spicexplorer_waveview.measure.measure_dataset`) or `sim.raw(run)`.
    """
    r = sim.run(deck, tag)
    return {**r.measures, **{k: float("nan") for k in r.failed}}


def evaluate(design: Design, tag: str, *, record: bool = True) -> dict:
    """One sizing point through the scorecard; one ledger row unless `record=False`."""
    deck, t0 = design.deck(), time.perf_counter()
    values = measure(deck, tag)
    viol = violations(H.spec, values)
    if not record:
        return {**values, "violations": viol}
    return log_run(H, tag, values, deck=deck, wall=time.perf_counter() - t0, violations=viol,
                   design=design.as_dict())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lab.metrics")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the frozen reference no longer reproduces its certified scorecard")
    ap.parse_args(argv)
    if not H.reference_scorecard or not H.path(H.reference_scorecard).exists():
        print("SKIP: no reference certified yet (harness.yaml `reference_scorecard:` is empty); "
              "certify one, `make freeze`, then compare it here")
        return 0
    print(f"implement the drift check against {H.reference_scorecard} "
          "(simulate the frozen decks, compare every column within its tolerance)")
    return 1


if __name__ == "__main__":  # `make check`
    sys.exit(main())
