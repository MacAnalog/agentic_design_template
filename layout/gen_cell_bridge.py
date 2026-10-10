#!/usr/bin/env python3
"""Commercial-kit layout generator skeleton (`lane: bridge`): rename to `gen_<cell>_bridge.py` and fill it in.

The open-lane twin is `layout/gen_cell.py` (gdsfactory -> GDS). On a commercial kit the cell is
built as a `layout` cellview in the design's OA library on the EDA server, from the kit's own
PCells, so this generator returns data instead of geometry: a
`spicexplorer_layout.backends.<editor>.LayoutPlan` (the module path is in `plan()` below). The
platform's backend resolves the plan against the kit file and writes one SKILL file that builds
the cell; `make layout-flow` (on `lane: bridge`) then streams it out and runs one batch DRC, LVS
and PEX on the EDA server.

**The layout of record is this file, not the cellview.** Every claim about the cell is
re-derived from it (`.claude/skills/layout-evidence/SKILL.md`).

Generator contract (`spicexplorer_orchestration.workflows.layout_kit`), which `make layout-flow`
and an optimizer rely on:

* ``LayoutParams``: a frozen dataclass; every field is a layout knob with a default.
* ``BOUNDS: dict[str, tuple[float, float]]``: the legal range per knob.
* ``plan(params: dict, kit) -> LayoutPlan``: ``params`` is the ``--params`` JSON (its
  ``"sizing"`` entry, if any, is the path of the design's sizing file); ``kit`` is the
  ``spicexplorer_core.kit.Kit`` that ``$SX_KIT_FILE`` names. Coordinates are micrometres.
* No ``write_lvs_reference``: on this lane LVS compares the layout with the cell's schematic
  view in the same OA library (the schematic of record, ported by the `schematic-of-record`
  skill, Stage B), netlisted on the EDA server.

**Every kit fact is read from the kit file by name, never typed in here.** This repository may be
public and the kit is under NDA: a device master, a layer number or a rule value written in this
file is a disclosure, and a wrong one is a cell built against a kit nobody checked. Read them as

* ``kit.device("nmos")``: the master of a device role; ``.cdf_name("l")`` its CDF parameter name;
* ``kit.layer("metal1")`` / ``kit.layer("pins.metal1")``: a layer key's layer-purpose pair;
* ``kit.rule("<name>")``: a layout rule in micrometres, from the kit file's ``layout_rules:``;
* ``kit.snap(x)``: ``x`` on the kit's manufacturing grid.

The plan names roles and layer keys (``nmos``, ``metal1``); the backend maps them to the kit's
names when it writes the SKILL. The rule digest and layout shortcuts of the kit are in the linked
``pdk-<id>`` skill (doc/environment.md, row `kit skills`).

**The two rules of `gen_cell.py` hold here too.** Device sizes come from the sizing file, never
from ``LayoutParams``; and overlapping metal of two nets is one legal polygon, so a short between
them passes DRC and only LVS finds it.

Run it through `make layout-flow` (or `workflows.layout --tech '$SX_KIT_FILE'`) in the
orchestration venv, which has the layout backend. This module imports the backend inside
`plan()`, so it loads in any interpreter.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CELL = "<cell>"
#: the device roles this cell places; each must be a role in the kit file's `devices.roles`
ROLES: tuple[str, ...] = ("nmos", "pmos")
#: the `params` entry that is not a layout knob: the path of the design's sizing file
SIZING_KEY = "sizing"


@dataclasses.dataclass(frozen=True)
class LayoutParams:
    """Free layout constants (um): the layout-optimizer search space. No device sizes here."""

    dev_gap: float = 1.0  # x gap between device footprints in a row
    row_gap: float = 2.0  # y gap between the n and p rows
    rail_w: float = 1.0  # supply rail width


BOUNDS: dict[str, tuple[float, float]] = {
    "dev_gap": (0.5, 4.0),
    "row_gap": (1.0, 6.0),
    "rail_w": (0.5, 3.0),
}


def layout_params(params: Mapping[str, Any]) -> LayoutParams:
    """`params` (the ``--params`` JSON) as `LayoutParams`, every knob inside its `BOUNDS`.

    An unknown key is an error, not ignored: a misspelt knob would leave the default in place
    while the run records the value it was asked for.
    """
    fields = {f.name for f in dataclasses.fields(LayoutParams)}
    knobs = {k: v for k, v in params.items() if k != SIZING_KEY}
    unknown = sorted(set(knobs) - fields)
    if unknown:
        raise ValueError(
            f"{CELL}: unknown layout knob(s) {unknown}; the knobs are {sorted(fields)}"
        )
    p = LayoutParams(**{k: float(v) for k, v in knobs.items()})
    for name, (lo, hi) in BOUNDS.items():
        v = getattr(p, name)
        if not lo <= v <= hi:
            raise ValueError(f"{CELL}: {name}={v} is outside BOUNDS [{lo}, {hi}]")
    return p


def load_sizing(path: str | Path | None) -> dict[str, Any]:
    """The device sizes, read from the design's own file, never copied into this module."""
    if not path:
        return {}
    return json.loads(Path(path).read_text())


def plan(params: Mapping[str, Any], kit: Any) -> Any:
    """Place and route the cell; return the `LayoutPlan` the backend writes as SKILL."""
    from spicexplorer_layout.backends.virtuoso import LayoutPlan

    p = layout_params(params)
    sizing = load_sizing(params.get(SIZING_KEY))
    masters = {role: kit.device(role) for role in ROLES}  # a missing role fails here, by name
    lp = LayoutPlan(CELL)
    raise NotImplementedError(
        f"draw {CELL} into the LayoutPlan: place {sorted(masters)} from the sizing file "
        f"({len(sizing)} entries) with LayoutParams {dataclasses.asdict(p)}, route on kit layer "
        f"keys, put a pin on every port net (the pins become the LVS and PEX port names), and "
        f"return the plan ({type(lp).__name__})"
    )
