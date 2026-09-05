"""Regenerate this experiment's README.md from out/*.json (run after run.py).

Committed beside `run.py` so the tables and the verdict sentence regenerate from a fresh
checkout instead of being retyped — a number typed into prose drifts from the run that
produced it, and nobody can tell when it did.

    uv run --no-sync python experiments/NNN-<technique>/mk_readme.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from design import exp  # noqa: E402

EXP = Path(__file__).resolve().parent
KEYS = ["label"]        # + the scorecard columns this experiment reports
HEAD: dict[str, str] = {}   # {key: column heading} where the raw key reads badly


def main() -> int:
    rows = exp.load(EXP / "out")
    md = f"""# {EXP.name.split('-')[0]} — <technique>

**Paper(s):** <handles from pdf/INDEX.md, or none>
**Hypothesis:** <falsifiable: what moves, by how much, measured how>
**Control:** <what is held or re-allocated so the effect is attributable>
**Verdict:** <CONFIRMED | FALSIFIED | PARTLY … — the sentence, with the numbers interpolated>

Reproduce: `<PREFIX>_EXP={EXP.name.split('-')[0]} uv run --no-sync python {EXP.name}/run.py`,
then `mk_readme.py`. Every row below is a ledger row (`make runs ARGS="--exp {EXP.name.split('-')[0]}"`).

## Results

{exp.md(rows, KEYS, header=HEAD)}

{exp.verdicts(rows)}

![sweep](figs/sweep.png)

## Lessons to graduate

<entries for doc/journal/ at close-out, each with its ledger tag>
"""
    (EXP / "README.md").write_text(md)
    print("README written", len(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
