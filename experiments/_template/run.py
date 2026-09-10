"""NNN — the experiment. Everything simulated here is produced by THIS file.

    <PREFIX>_EXP=NNN uv run --no-sync python experiments/NNN-<technique>/run.py

Convention (both instantiations, and a review finding in each): `run.py` simulates and writes
`out/*.json`, `figs/*.png` and `tables/*.csv`; `mk_readme.py` beside it regenerates `README.md`
from those files. `out/` is git-ignored working data; `figs/`, `tables/` and the two scripts are
COMMITTED — so a reader on a fresh checkout can see how every number and every figure was made,
and re-make them. A figure or a table that only exists because somebody once ran something by
hand is not evidence.

Those three directories are also the only places an experiment may leave a committed artefact
(`artifact-home` in `scripts/lint.py`). Raw simulator output — rawfiles, work directories, logs —
never enters the repo at all; it stays in the scratch root.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from design import bench, exp, metrics, plot  # noqa: E402
from design.dut import Design  # noqa: E402

# `bench` is imported on purpose: an experiment that post-processes a run reports through
# `bench.reduce` — the SAME reduction `metrics.run_decks` certifies — so this report and the
# frozen scorecard cannot disagree. The same maths written here instead is uncertifiable.

EXP = Path(__file__).resolve().parent
OUT, FIGS, TABLES = EXP / "out", EXP / "figs", EXP / "tables"


def designs() -> dict[str, Design]:
    """{label: Design} — the control FIRST, then one design per arm of the hypothesis.

    A knob only moves against a control; a batch with no control measures the weather.
    """
    return {"control": Design(), "<arm>": Design()}


def main() -> int:
    exp.set_exp(EXP.name.split("-")[0])          # stamps every ledger row with NNN
    rows = exp.run_batch(designs(), metrics.evaluate, prefix=f"{EXP.name}_")
    exp.save(rows, OUT)                          # out/rows.json — mk_readme.py reads this
    exp.csv(rows, TABLES / "rows.csv")           # the same numbers a later run can diff
    plot.series(rows, FIGS / "sweep.png", x="<knob>", ys=[r.key for r in plot.SPEC.values()][:3],
                title=EXP.name)
    print(exp.md(rows, ["label", *[r.key for r in plot.SPEC.values()]]))
    print()
    print(exp.verdicts(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
