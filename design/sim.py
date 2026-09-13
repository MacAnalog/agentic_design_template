"""WHICH simulator lane this design runs on — one decision, taken from `harness.yaml`.

`design.sim` is the name the rest of the repo imports (`design.metrics`, `design.exp`,
`design.plot`, `layout/signoff.py`, every experiment). This module does not implement a lane: it
reads `lane:` from `harness.yaml` and **replaces itself in `sys.modules`** with the lane module
that key names. `from design import sim` therefore hands back the lane ITSELF — `sim.run`,
`sim.work`, `sim.preflight`, `sim.DECK_VARS` are the lane's own objects, not copies of its names.
That matters beyond tidiness: a star-import would copy the lane's module-level policy constants
into a second namespace, and every later assignment to one of them (a test, an experiment pinning
`DECK_VARS`) would change the copy while the lane kept reading its own.

Two lanes ship with the template:

| `lane:` | module | what it drives |
|---|---|---|
| `ngspice` (default) | `design/sim_ngspice.py` | native ngspice on this machine, over the platform's `spicexplorer_core.spice_engine.run_deck` |
| `bridge` | `design/sim_bridge.py` | a commercial kit, whose models load only in the vendor simulator on the lab's EDA server: the deck goes there through the lab's bridge and the results come back |

**`lane:` absent is the open lane, and nothing about it behaves differently.** A design cut before
this split, or any design on an open PDK, never writes the key: the default is `ngspice`, and the
module it selects is template v2.07's `design/sim.py` under a new file name — it gained a `main()`
entry point, a docstring paragraph and a neutralised comment, and nothing that runs. No new
dependency is installed. The bridge lane is opt-in twice over — the key, and the platform package
that `pyproject.toml` tells a commercial-PDK design to add.

The key is read through `getattr(H, "lane", …)` so this module works against a platform that does
not carry the field yet; such a platform REJECTS the key itself (`harness.yaml: unknown keys
['lane']`) when a design writes it, which is a loud, accurate error rather than a silent default.
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

from spicexplorer_harness import load

REPO = Path(__file__).resolve().parents[1]

# `lane:` -> the module in this package that implements it. A closed set on purpose: a lane the
# design does not ship is a typo in `harness.yaml`, not an extension point. Adding a lane means
# adding its module here, beside its key.
LANES: dict[str, str] = {"ngspice": "sim_ngspice", "bridge": "sim_bridge"}
DEFAULT_LANE = "ngspice"

__all__ = ["LANES", "DEFAULT_LANE", "LANE", "lane_name", "module_name"]


def module_name(lane: str) -> str:
    """The module implementing `lane`; an empty value is the default, an unknown one is refused.

    The refusal names every lane that ships, because the failure it catches is a plausible
    spelling of a lane that exists (`remote`, `commercial`, the simulator's own name) landing in
    `harness.yaml` and being read as "no lane, use the default" — which would run a commercial
    design's benches on the wrong simulator, quietly.
    """
    key = (lane or "").strip() or DEFAULT_LANE
    if key not in LANES:
        raise ValueError(
            f"harness.yaml says `lane: {lane}`, which is not a lane this design ships. Known "
            f"lanes: {', '.join(sorted(LANES))}. Leave `lane:` out for the default "
            f"({DEFAULT_LANE}).")
    return LANES[key]


def lane_name() -> str:
    """`lane:` from `harness.yaml`, else the default — the open lane."""
    return (getattr(load(REPO), "lane", "") or "").strip() or DEFAULT_LANE


LANE = lane_name()
_mod = import_module(f".{module_name(LANE)}", __package__)

# The selection travels WITH the lane module, so `design.sim.LANE` answers "which lane am I on"
# after the swap below has made this module unreachable by name.
for _n in ("LANE", "LANES", "DEFAULT_LANE", "lane_name", "module_name"):
    setattr(_mod, _n, globals()[_n])

if __name__ == "__main__":          # `make doctor` = `python -m design.sim`
    sys.exit(_mod.main())

# THE swap. The import system re-reads `sys.modules[__name__]` after this module's body has run
# and binds THAT object as `design.sim`, so every importer — including one that already wrote
# `import design.sim` — gets the lane module.
sys.modules[__name__] = _mod
