"""NNN — the experiment. Everything simulated here is produced by THIS file.

    <PREFIX>_EXP=NNN uv run --no-sync python experiments/NNN-<technique>/run.py

Convention (both instantiations, and a review finding in each): `run.py` simulates and writes
`out/*.json` + `figs/*.png`; `mk_readme.py` beside it regenerates `README.md` from those files.
`out/` is git-ignored working data, `figs/` and the two scripts are COMMITTED — so a reader on a
fresh checkout can see how every number and every figure was made, and re-make them. A figure or
a table that only exists because somebody once ran something by hand is not evidence.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from design import exp, metrics, plot  # noqa: E402
from design.dut import Design  # noqa: E402

EXP = Path(__file__).resolve().parent
OUT, FIGS = EXP / "out", EXP / "figs"


def designs() -> dict[str, Design]:
    """{label: Design} — the control FIRST, then one design per arm of the hypothesis.

    A knob only moves against a control; a batch with no control measures the weather.
    """
    return {"control": Design(), "<arm>": Design()}


def main() -> int:
    exp.set_exp(EXP.name.split("-")[0])          # stamps every ledger row with NNN
    rows = exp.run_batch(designs(), metrics.evaluate, prefix=f"{EXP.name}_")
    exp.save(rows, OUT)                          # out/rows.json — mk_readme.py reads this
    plot.series(rows, FIGS / "sweep.png", x="<knob>", ys=[r.key for r in plot.SPEC.values()][:3],
                title=EXP.name)
    print(exp.md(rows, ["label", *[r.key for r in plot.SPEC.values()]]))
    print()
    print(exp.verdicts(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
