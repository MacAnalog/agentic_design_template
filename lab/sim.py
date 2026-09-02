"""The simulator lane: is it alive, and run one deck in its own work dir.

Reference implementation: the LPF challenge repo's `lab/ngspice.py` (docker | native lanes
selected by one env var, per-run work dirs namespaced per checkout, and a fatal-string scan of
the log -- ngspice exits 0 after a failed operating point and leaves a rawfile full of zeros).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

LANE_ENV = "SIM_NGSPICE"   # non-empty => native binary; empty => the docker image


def lane() -> str:
    return "native" if os.environ.get(LANE_ENV) else "docker"


def preflight() -> dict:
    """Run a one-device `.op` through the lane and report what it produced."""
    return {"lane": lane(), "ok": False,
            "note": "implement lab.sim.preflight (see the module docstring)"}


def run(deck: str, tag: str) -> Path:
    """Simulate `deck` under a per-run directory and return it; raise on a failed run."""
    raise NotImplementedError("implement lab.sim.run for this lane")


if __name__ == "__main__":  # `make doctor`
    r = preflight()
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["ok"] else 1)
