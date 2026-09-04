#!/usr/bin/env python3
"""Parameterized layout generator skeleton — rename to `gen_<cell>.py` and fill it in.

**The layout of record is this file, not the GDS.** Every claim about the cell is re-derived
from it (`.claude/skills/layout-evidence/SKILL.md`).

Generator contract (`spicexplorer_layout.gen.load_generator`), which the platform's builder,
the CLI (`spicexplorer-layout build|knobs|snapshot`) and an optimizer all rely on:

* ``LayoutParams`` — a frozen dataclass; every field is a layout knob with a default.
* ``BOUNDS: dict[str, tuple[float, float]]`` — the legal range per knob. A knob without a
  bound cannot be searched; a bound that admits a DRC violation wastes a whole trial.
* ``build(params, sizing=None) -> gdsfactory.Component``.
* ``write_lvs_reference(params, sizing, out)`` — the netlist LVS compares the GDS against.

**Two rules the LDO instantiation paid for**

1. *Device sizes are never layout knobs.* W/L/m come from `sizing` — read the design's own
   sizing file / `design.json` here rather than copying numbers, so a re-sized cell redraws
   itself with no edit in this file. `LayoutParams` holds only free layout constants (gaps,
   pitches, rail widths, segment counts).
2. *Claim every net's metal.* Overlapping Metal1 merges into ONE legal polygon: a knob change
   can short two nets with DRC still at zero violations — only LVS sees it
   (`doc/journal/…metal1-stub-shorts-are-drc-invisible.md`). Route through the obstacle map
   below so a collision raises at build time instead of surviving to sign-off.

Run it with the interpreter that has gdsfactory + the PDK cells (`$<PREFIX>_GDS_PYTHON`,
`doc/environment.md`), never the repo venv.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

CELL = "<cell>"
GRID = 0.005  # PDK manufacturing grid (um); snap every coordinate


@dataclasses.dataclass(frozen=True)
class LayoutParams:
    """Free layout constants (um) — the layout-optimizer search space. No device sizes here."""

    dev_gap: float = 3.0      # x gap between devices in a row
    track_pitch: float = 0.7  # routing-channel track pitch
    rail_w: float = 0.8       # supply rail width
    rail_gap: float = 1.6     # active edge -> rail centre
    blk_gap: float = 6.0      # gap between the device stack and the passive blocks


BOUNDS: dict[str, tuple[float, float]] = {
    "dev_gap": (2.0, 6.0), "track_pitch": (0.65, 1.2), "rail_w": (0.5, 2.0),
    "rail_gap": (1.4, 2.5), "blk_gap": (4.0, 15.0),
}


def snap(v: float) -> float:
    return round(round(v / GRID) * GRID, 4)


class Obstacles:
    """Per-net metal claims: the guard that makes a DRC-invisible short a build-time error.

    Every horizontal run and every vertical column is `claim`ed for its net before it is drawn.
    Two nets that overlap on the same layer raise here; the same net may overlap itself freely.
    `free_column` walks outward from a preferred x until it finds one no other net holds — an
    exhausted search is a floorplan message ("widen dev_gap"), not a silent overlap.
    """

    def __init__(self, clearance: float = 0.21):
        self.clearance = clearance                      # min space rule of the routing layer
        self.boxes: list[tuple[str, str, float, float, float, float]] = []

    def claim(self, net: str, layer: str, x0: float, y0: float, x1: float, y1: float) -> None:
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        c = self.clearance
        for onet, olayer, ox0, oy0, ox1, oy1 in self.boxes:
            if olayer != layer or onet == net:
                continue
            if x0 - c < ox1 and ox0 < x1 + c and y0 - c < oy1 and oy0 < y1 + c:
                raise AssertionError(
                    f"{layer}: net {net!r} would merge with {onet!r} at "
                    f"({x0:.3f},{y0:.3f})-({x1:.3f},{y1:.3f}) — overlapping metal is one legal "
                    f"polygon, so DRC will not see this short; move the run or widen the gap")
        self.boxes.append((net, layer, x0, y0, x1, y1))

    def free_column(self, net: str, x: float, y0: float, y1: float, layer: str,
                    w: float = 0.2, step: float = 0.6, tries: int = 24) -> float:
        for k in range(tries):
            for cand in ((x + k * step), (x - k * step)):
                try:
                    self.claim(net, layer, cand - w / 2, y0, cand + w / 2, y1)
                    return snap(cand)
                except AssertionError:
                    continue
        raise AssertionError(f"no free {layer} column for {net!r} near x={x:.3f}: "
                             "widen LayoutParams.dev_gap or re-order the row")


def load_sizing(path: str | Path | None = None) -> dict:
    """The device sizes, read from the design's own file — never copied into this module."""
    if path is None:
        return {}
    return json.loads(Path(path).read_text())


def build(params: LayoutParams = LayoutParams(), sizing: dict | None = None):
    """Place and route the cell; return the gdsfactory Component."""
    import gdsfactory as gf  # noqa: F401  (the generator interpreter, not the repo venv)

    _obs = Obstacles()  # claim every run through it; see the class docstring
    raise NotImplementedError(
        f"draw {CELL}: place the devices from `sizing`, route through the obstacle map, "
        "label every pin net (the labels become LVS/PEX pin names)")


def write_lvs_reference(params: LayoutParams = LayoutParams(), sizing: dict | None = None,
                        out: str | Path = f"{CELL}_lvs.spice") -> Path:
    """The netlist LVS compares the GDS against.

    Emit it from the CERTIFIED binding (the same source `lab.dut.Design` builds decks from), not
    from this generator's own device table — a golden netlist written by the thing under test
    proves nothing (LDO review-002).
    """
    raise NotImplementedError("write the LVS reference from the certified netlist source")


def main() -> None:
    ap = argparse.ArgumentParser(description=f"build {CELL}")
    ap.add_argument("-o", "--out", default=f"{CELL}.gds")
    ap.add_argument("--lvs", default=None, help="also write the LVS reference netlist here")
    ap.add_argument("--sizing", default=None, help="design.json / sizing file the sizes come from")
    ap.add_argument("--params", default=None, help="JSON overrides for LayoutParams")
    a = ap.parse_args()
    p = LayoutParams(**json.loads(a.params)) if a.params else LayoutParams()
    sizing = load_sizing(a.sizing)
    c = build(p, sizing)
    c.write_gds(a.out)
    bbox = c.bbox()
    print(f"{CELL}: {a.out}  area um2: {round((bbox.right - bbox.left) * (bbox.top - bbox.bottom))}")
    if a.lvs:
        write_lvs_reference(p, sizing, a.lvs)


if __name__ == "__main__":
    main()
