"""Experiment helpers: a labelled batch through one scorer, markdown tables, `out/` files.

An experiment's `run.py` builds `{label: Design}`, calls `run_batch(designs, metrics.evaluate)`,
saves `out/rows.json`, draws its figures with `design.plot` and prints the markdown that graduates
into its README.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from spicexplorer_harness import batch, violations

from .sim import H


def set_exp(nnn: str) -> None:
    """Stamp every ledger row of this process with experiment `nnn` (unless already set)."""
    os.environ.setdefault(H.exp_env, nnn)


def run_batch(designs: dict, score: Callable, *, prefix: str = "",
              workers: int | None = None) -> list[dict]:
    """`score(design, tag) -> row` for every design in parallel (`jobs_env` wide); a failure is a row with `error`."""
    items = list(designs.items())
    rows = batch(items, lambda it: score(it[1], f"{prefix}{it[0]}"), workers=workers, env=H.jobs_env)
    out = []
    for (label, d), r in zip(items, rows):
        if isinstance(r, Exception):
            out.append({"label": label, "error": str(r)[:300],
                        "design": d.as_dict() if hasattr(d, "as_dict") else str(d)})
        else:
            out.append({"label": label, **r})
    return out


def fmt(v, p: int = 2) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        if v != v:
            return "nan"
        return f"{v:.{p}f}" if abs(v) < 1e4 else f"{v:.3g}"
    return "—" if v is None else str(v)


def md(rows: list[dict], keys: list[str], *, header: dict | None = None, p: int = 2) -> str:
    """A markdown table of `keys` per row (`header` renames columns); the finding, not prose."""
    header = header or {}
    head = "| " + " | ".join(header.get(k, k) for k in keys) + " |"
    body = ["| " + " | ".join(fmt(r.get(k), p) for k in keys) + " |" for r in rows]
    return "\n".join([head, "|" + "---|" * len(keys), *body])


def verdicts(rows: list[dict]) -> str:
    """One bullet per row: PASS, the violations, or the error."""
    out = []
    for r in rows:
        v = r.get("violations")
        out.append(f"- `{r.get('label')}`: "
                   + ("PASS" if v == [] else "; ".join(v) if v else r.get("error", "?")))
    return "\n".join(out)


def passes(row: dict, keys=None) -> bool:
    """Spec verdict on a row, optionally restricted to `keys` (e.g. the at-rate rows of a frontier)."""
    return not violations([r for r in H.spec if keys is None or r.key in keys], row)


def save(rows: list[dict], out_dir: Path, name: str = "rows.json") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / name
    p.write_text(json.dumps(rows, indent=1, default=str) + "\n")
    return p


def load(out_dir: Path, name: str = "rows.json") -> list[dict]:
    return json.loads((Path(out_dir) / name).read_text())
