"""Fast scorecard: build the deck, simulate, measure, check the box, log the row."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from spicexplorer_harness import load, log_run, violations

from .dut import Design

H = load(Path(__file__).resolve().parents[1])


def measure(deck: str) -> dict:
    raise NotImplementedError("run `deck` on the simulator lane and return {metric_key: value}")


def evaluate(design: Design, tag: str) -> dict:
    deck, t0 = design.deck(), time.perf_counter()
    values = measure(deck)
    return log_run(H, tag, values, deck=deck, wall=time.perf_counter() - t0,
                   violations=violations(H.spec, values), design=design.as_dict())


if __name__ == "__main__":  # `make check`: the reference must reproduce its certified scorecard
    sys.exit("no reference certified yet: freeze one (make freeze) and compare it here")
