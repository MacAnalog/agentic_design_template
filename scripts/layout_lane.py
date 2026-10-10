#!/usr/bin/env python3
"""`make layout-flow`: the lane's arguments for `workflows.layout`, read from `harness.yaml`.

`lane:` picks the layout lane the same way it picks the simulator lane (`design/sim.py`):

- **absent (the open lane):** `--generator <GEN>`, with `GEN` defaulting to `layout/gen_cell.py`
  (gdsfactory -> GDS, KLayout DRC/LVS, kpex). Nothing else is added, so the open lane runs as it
  did before this script existed.
- **`bridge` (a commercial kit):** `--generator <GEN>` (default `layout/gen_cell_bridge.py`), then
  `--tech '$SX_KIT_FILE' --lib <LIB>` and `--workarea <WORKAREA>` when one is given. An empty
  `LIB` (`WORKAREA`) falls back to `$<PREFIX>_OA_LIB` (`$<PREFIX>_WORKAREA`), the variables
  `layout/signoff.py` reads, so one export serves both entry points; `<PREFIX>` is derived from
  `exp_env` the way the platform derives it (`LDO_EXP` -> `LDO`, a bare `EXP` -> `SIM`). The workflow
  reads the kit file `$SX_KIT_FILE` names, builds the cell in the OA library `<LIB>` on the EDA
  server from the generator's `LayoutPlan`, and runs one batch DRC/LVS/PEX there. The literal
  `$SX_KIT_FILE` is passed, not its value, so the kit path never reaches the run's verdicts or
  its ledger row.

On the bridge lane an unset `SX_KIT_FILE`, or no `LIB` and no `$<PREFIX>_OA_LIB`, exits 2 with one line naming what is
missing, before the workflow starts. Any other `lane:` value exits 2 as well: an unknown lane is
not quietly the open one.

Standard library only (it runs from `make` in any interpreter). The arguments are printed one per
line; none of them contains white space, so the Makefile's `$$(...)` splits them as written.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdk_links  # the sibling module, found through the line above

REPO = Path(__file__).resolve().parents[1]

OPEN_GENERATOR = "layout/gen_cell.py"
BRIDGE_GENERATOR = "layout/gen_cell_bridge.py"
KIT_FILE_ENV = "SX_KIT_FILE"
#: the `tech` value that tells `workflows.layout` to read the kit file `$SX_KIT_FILE` names
KIT_TECH = "$" + KIT_FILE_ENV
LANES = ("", "ngspice", "bridge")
#: `$<PREFIX>_OA_LIB` / `$<PREFIX>_WORKAREA`: the fallbacks `layout/signoff.py` reads as well
OA_LIB_SUFFIX = "_OA_LIB"
WORKAREA_SUFFIX = "_WORKAREA"
# an argument this script prints must survive the Makefile's word splitting unchanged
_NO_SPACE = re.compile(r"^\S+$")


class LaneError(ValueError):
    """The lane cannot run as configured; the message names the missing piece and its fix."""


def lane_args(
    lane: str,
    *,
    generator: str = "",
    lib: str = "",
    workarea: str = "",
    env: dict[str, str] | None = None,
    prefix: str = "SIM",
) -> list[str]:
    """The `workflows.layout` arguments for `lane` (the `lane:` value of `harness.yaml`).

    On the bridge lane an empty `lib` / `workarea` is read from `$<prefix>_OA_LIB` /
    `$<prefix>_WORKAREA`.
    """
    environ = os.environ if env is None else env
    if lane not in LANES:
        raise LaneError(
            f"harness.yaml declares lane: {lane}; the layout flow knows {[x for x in LANES if x]} "
            "(absent = the open lane)"
        )
    bridge = lane == "bridge"
    gen = generator or (BRIDGE_GENERATOR if bridge else OPEN_GENERATOR)
    args = ["--generator", gen]
    if not bridge:
        return _checked(args)
    if not environ.get(KIT_FILE_ENV, "").strip():
        raise LaneError(
            f"lane: bridge needs {KIT_FILE_ENV}: export {KIT_FILE_ENV}=<the kit YAML in the "
            "private repo that owns the kit> (doc/environment.md, row `kit file`)"
        )
    lib = lib or environ.get(prefix + OA_LIB_SUFFIX, "").strip()
    workarea = workarea or environ.get(prefix + WORKAREA_SUFFIX, "").strip()
    if not lib:
        raise LaneError(
            "lane: bridge builds the cell in an OA library on the EDA server: pass OA_LIB=<library> "
            f"or export {prefix}{OA_LIB_SUFFIX}=<library> (doc/environment.md, row `OA library`)"
        )
    args += ["--tech", KIT_TECH, "--lib", lib]
    if workarea:
        args += ["--workarea", workarea]
    return _checked(args)


def _checked(args: list[str]) -> list[str]:
    bad = [a for a in args if not _NO_SPACE.match(a)]
    if bad:
        raise LaneError(f"layout-flow arguments may not contain white space: {bad}")
    return args


def _harness_text(root: Path) -> str:
    try:
        return (root / "harness.yaml").read_text()
    except OSError:
        return ""


def declared_lane(root: Path = REPO) -> str:
    """The top-level `lane:` of `root/harness.yaml`, or "" when it is absent or unreadable."""
    return pdk_links.declared(_harness_text(root), "lane")


def env_prefix(root: Path = REPO) -> str:
    """The harness env-name prefix, from `exp_env` (default `EXP`) exactly as the platform derives
    it (`spicexplorer_harness.config.Harness`) and as `layout/signoff.py`'s `_prefix` does."""
    exp_env = pdk_links.declared(_harness_text(root), "exp_env") or "EXP"
    return exp_env[:-4] if exp_env.endswith("_EXP") and len(exp_env) > 4 else "SIM"


def main(argv: Sequence[str] | None = None, root: Path = REPO) -> int:
    ap = argparse.ArgumentParser(description="the layout lane's workflows.layout arguments")
    ap.add_argument("--gen", default="", help="generator module (default: the lane's skeleton)")
    ap.add_argument("--lib", default="", help="bridge lane: the OA library of the cell")
    ap.add_argument("--workarea", default="", help="bridge lane: the account's workarea")
    a = ap.parse_args(argv)
    try:
        args = lane_args(
            declared_lane(root),
            generator=a.gen,
            lib=a.lib,
            workarea=a.workarea,
            prefix=env_prefix(root),
        )
    except LaneError as exc:
        print(f"make layout-flow: {exc}")
        return 2
    print("\n".join(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
