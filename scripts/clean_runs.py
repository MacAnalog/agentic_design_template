#!/usr/bin/env python3
"""`make clean-runs` and the scratch report `make doctor` prints: the raw record is scratch.

**A raw simulation record is scratch, not evidence.** Reduce it, commit the reduction, delete the
raw. Nothing in the flow used to own that last step — the lane writes records and never revisits
them, `make clean` removes a whole checkout's work dir (too coarse to run mid-campaign), and an
agent told to reduce off disk was never told the raw was then its to remove. One overnight
campaign left 212 GB of transient records in one account's scratch, every one of them already
reduced to a committed table, and the owner heard about it from the workstation admin
(template#37).

So this file owns deletion, and it is deliberately timid, because the two mistakes do not cost the
same: a record deleted too early costs one re-simulation, a record nobody deletes costs a shared
machine. A run directory is removed only when ALL of these hold:

* it is a directory directly under `<work>/runs/`, outside the repo;
* it carries no `.busy` marker (another run may hold it — this is what makes the sweep safe to
  run mid-campaign, unlike `make clean`);
* a ledger row names its label, and that row is not a bare `sim_error` — i.e. the reduction the
  raw record exists for has been made and recorded;
* its simulator log has not been touched for `--age` hours (default 24).

Everything it does NOT delete is printed with the reason, so the output answers "why is my scratch
still full?" without a second command.

**Not a reimplementation of `spicexplorer-harness prune`.** That is the platform's rawfile-level
retention (the `raws` ledger column, `keep_raw:` policy, an orphan pass) and it is the right tool
for thinning rawfiles inside runs that are still wanted. This is the coarser, design-side sweep:
whole run directories of THIS checkout, matched by label, gated on age. Use both.

Pure where it matters: `label_of`, `reduced`, `decide` and `scan` take their inputs as arguments
and touch nothing, which is what `tests/test_scratch.py` drives.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from spicexplorer_harness import ledger as LG  # noqa: E402
from spicexplorer_harness import load  # noqa: E402
from spicexplorer_harness.retention import human_bytes  # noqa: E402

#: Default age gate, in hours: a record whose log was written more recently is still warm.
AGE_HOURS = 24.0
#: `make doctor` warns above this many GB of scratch in THIS checkout's work dir.
WARN_GB_ENV = "SX_SCRATCH_WARN_GB"
DEFAULT_WARN_GB = 50.0
#: What a simulator log is called, as a glob rather than a list of names: each lane names its log
#: after its own tool, and this repo may not write a commercial simulator's name (`denylist:` in
#: harness.yaml). Every lane writes `<tool>.out` or `<something>.log` into the run dir.
LOG_GLOBS = ("*.out", "*.log")
BUSY = ".busy"
#: A run directory is `<slug(label)>-<sha256(deck)[:8]>`; the hash is over the RESOLVED deck while
#: the ledger's `deck` column hashes the PORTABLE text, so the two never have to agree — matching
#: is on the label alone, and the hash is only stripped off the directory name.
_RUN_HASH = re.compile(r"-[0-9a-f]{8}$")
_SLUG = re.compile(r"[^A-Za-z0-9_.-]+")

__all__ = ["AGE_HOURS", "WARN_GB_ENV", "DEFAULT_WARN_GB", "LOG_GLOBS", "BUSY", "slug",
           "label_of", "rows_by_label", "reduced", "log_age_s", "dir_bytes", "decide", "scan",
           "refuse", "remove", "work_dir", "usage", "warn_gb", "report", "main"]


# ------------------------------------------------------------------ pure --------------

def slug(s: str) -> str:
    """A label as both lanes spell it in a directory name (`[^A-Za-z0-9_.-]` -> `_`)."""
    return _SLUG.sub("_", str(s)).strip("_")


def label_of(name: str) -> str:
    """The run label behind a directory name: `ac__gain-1a2b3c4d` -> `ac__gain`."""
    return slug(_RUN_HASH.sub("", name))


def rows_by_label(rows: list[dict]) -> dict[str, list[dict]]:
    """Ledger rows grouped by the label their `tag` becomes in a directory name."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        tag = slug(r.get("tag") or "")
        if tag:
            out.setdefault(tag, []).append(r)
    return out


def reduced(rows: list[dict]) -> bool:
    """Has this label's record been reduced to something the repo keeps?

    A row exists and at least one of them is not a `sim_error`. A row with no `status` column
    counts (an `evaluate` row is a scorecard, which is a reduction by definition); a label whose
    only rows say the simulation failed does NOT — that is exactly the record someone is about to
    open, and it keeps its raw.
    """
    return any(str(r.get("status", "")) != "sim_error" for r in rows)


def log_age_s(run: Path, now: float | None = None) -> float | None:
    """Seconds since the run's simulator log was last written; `None` when it has none.

    A run directory with no log never finished (or is not a run directory at all), so it is kept:
    the age gate is what proves nothing is still writing into it.
    """
    now = time.time() if now is None else now
    ages = []
    for pattern in LOG_GLOBS:
        for p in Path(run).glob(pattern):
            try:
                ages.append(now - p.stat().st_mtime)
            except OSError:
                continue
    return min(ages) if ages else None


def dir_bytes(path: Path) -> int:
    """Total size of the files under `path` (symlinks counted as the link, never followed)."""
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                continue
    return total


def decide(*, busy: bool, age_s: float | None, rows: list[dict], age_h: float) -> tuple[bool, str]:
    """`(delete?, why)` for one run directory. Pure: the whole selection rule, in one place.

    Order matters — the first reason that applies is the one printed, and the ones that protect a
    record come first, so a directory is never reported as "too young" when the real reason it
    survives is that nothing has reduced it.
    """
    if busy:
        return False, f"a run may be in progress ({BUSY} marker)"
    if not rows:
        return False, "no ledger row names this label — nothing has recorded a reduction of it"
    if not reduced(rows):
        return False, (f"the ledger says this label only ever failed to simulate "
                       f"({len(rows)} row(s), all sim_error) — the record is the evidence")
    if age_s is None:
        return False, f"no simulator log ({' or '.join(LOG_GLOBS)}) — the run did not finish"
    if age_s < age_h * 3600.0:
        return False, f"the simulator log is {age_s / 3600.0:.1f} h old (< AGE={age_h:g} h)"
    return True, (f"reduced ({len(rows)} ledger row(s)) and its log is "
                  f"{age_s / 3600.0:.1f} h old (>= AGE={age_h:g} h)")


def scan(runs: Path, by_label: dict[str, list[dict]], *, age_h: float = AGE_HOURS,
         now: float | None = None, sizes: bool = True) -> list[dict]:
    """One entry per run directory under `runs`:
    `{path, name, label, delete, why, rows, reduced, bytes}`."""
    now = time.time() if now is None else now
    out: list[dict] = []
    if not Path(runs).is_dir():
        return out
    for d in sorted(Path(runs).iterdir()):
        if not d.is_dir() or d.is_symlink():
            continue
        label = label_of(d.name)
        rows = by_label.get(label, [])
        age = log_age_s(d, now)
        delete, why = decide(busy=(d / BUSY).exists(), age_s=age, rows=rows, age_h=age_h)
        out.append({"path": d, "name": d.name, "label": label, "delete": delete, "why": why,
                    "rows": len(rows), "reduced": reduced(rows),
                    "bytes": dir_bytes(d) if sizes else 0})
    return out


# ------------------------------------------------------------------ deleting ----------

def refuse(path: Path, runs: Path, repo: Path = REPO) -> str | None:
    """Why `path` must not be removed, or `None`. The same shape as the platform's retention rules:
    a directory, directly under the work root's `runs/`, never inside the repo."""
    p = Path(path)
    try:
        rp = p.resolve()
    except OSError as exc:  # pragma: no cover - unresolvable path
        return f"{p} cannot be resolved ({exc})"
    if p.is_symlink():
        return f"{p} is a symlink"
    if not rp.is_dir():
        return f"{p} is not a directory"
    root = Path(repo).resolve()
    if rp == root or root in rp.parents:
        return f"{p} is inside the repo ({root}) — committed artefacts are never swept"
    if rp.parent != Path(runs).resolve():
        return f"{p} is not a run directory directly under {runs}"
    return None


def remove(entries: list[dict], runs: Path, *, dry_run: bool = False,
           repo: Path = REPO) -> tuple[list[dict], list[str]]:
    """Remove every entry marked `delete`; returns `(removed, refused)`."""
    removed: list[dict] = []
    refused: list[str] = []
    for e in entries:
        if not e["delete"]:
            continue
        why = refuse(e["path"], runs, repo)
        if why is not None:
            refused.append(why)
            continue
        if not dry_run:
            try:
                shutil.rmtree(e["path"])
            except OSError as exc:
                refused.append(f"{e['path']}: {exc}")
                continue
        removed.append(e)
    return removed, refused


# ------------------------------------------------------------------ this checkout -----

def work_dir() -> tuple[Path | None, str]:
    """This checkout's work root, from the lane itself (`<package>.sim.work()`), and a note.

    Resolved through the lane rather than re-derived here: WHERE runs go is the lane's policy
    (`$<work_env>`, else `$SX_SCRATCH/<design>-<checkout>`), and a second copy of that rule is a
    second thing to keep in step.
    """
    package = load(REPO).package
    try:
        sim = importlib.import_module(f"{package}.sim")
        return Path(sim.work()), ""
    except Exception as exc:  # noqa: BLE001 - reported, never raised: this runs inside `make doctor`
        return None, f"cannot resolve the work dir through {package}.sim: {exc}"


def warn_gb() -> float:
    """`$SX_SCRATCH_WARN_GB`, else 50 GB. `0` (or anything unparsable) disables the warning."""
    try:
        return float(os.environ.get(WARN_GB_ENV) or DEFAULT_WARN_GB)
    except ValueError:
        return DEFAULT_WARN_GB


def usage(work: Path | None) -> dict:
    """`{work, bytes, human, runs, over, warn_gb}` for one work root (missing dir -> zeroes)."""
    limit = warn_gb()
    rep = {"work": str(work or ""), "bytes": 0, "human": human_bytes(0), "runs": 0,
           "warn_gb": limit, "over": False}
    if work is None or not Path(work).is_dir():
        return rep
    runs = Path(work) / "runs"
    n = sum(1 for d in runs.iterdir() if d.is_dir()) if runs.is_dir() else 0
    total = dir_bytes(Path(work))
    rep.update(bytes=total, human=human_bytes(total), runs=n,
               over=bool(limit and total > limit * 1e9))
    return rep


def report(rep: dict, note: str = "") -> str:
    """The one-or-two line scratch report `make doctor` prints after the lane probe."""
    if not rep["work"]:
        return f"scratch: unknown — {note}" if note else "scratch: unknown"
    if not Path(rep["work"]).is_dir():
        return f"scratch: {rep['work']} does not exist yet (nothing has simulated in this checkout)"
    line = (f"scratch: {rep['work']} — {rep['human']} in {rep['runs']} run dir(s) "
            f"(warn above {rep['warn_gb']:g} GB, ${WARN_GB_ENV})")
    if rep["over"]:
        line += ("\nWARNING: this checkout's scratch is over the threshold. A raw simulation "
                 "record is scratch, not evidence: reduce it, commit the reduction, then "
                 "`make clean-runs` (it keeps anything unreduced, running, or younger than AGE).")
    return line


# ------------------------------------------------------------------ CLI ---------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="clean_runs.py",
        description="delete the run dirs whose reduction is recorded and whose log has gone cold")
    ap.add_argument("--age", type=float, default=AGE_HOURS, metavar="HOURS",
                    help=f"keep a run whose simulator log is younger than this (default {AGE_HOURS:g})")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, delete nothing")
    ap.add_argument("--report", action="store_true",
                    help="print this checkout's scratch usage and exit (what `make doctor` runs)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    work, note = work_dir()
    rep = usage(work)
    if a.report:
        print(json.dumps({**rep, "note": note}, indent=2) if a.json else report(rep, note))
        return 0
    if work is None:
        print(f"clean-runs: {note}")
        return 1
    runs = Path(work) / "runs"
    if not runs.is_dir():
        print(f"clean-runs: {runs} does not exist — nothing to clean")
        return 0
    entries = scan(runs, rows_by_label(LG.read(load(REPO))), age_h=a.age)
    removed, refused = remove(entries, runs, dry_run=a.dry_run)
    kept = [e for e in entries if not e["delete"]]
    if a.json:
        print(json.dumps({"work": str(work), "age_h": a.age, "dry_run": a.dry_run,
                          "removed": [e["name"] for e in removed],
                          "kept": [{"name": e["name"], "why": e["why"], "bytes": e["bytes"]}
                                   for e in kept],
                          "refused": refused,
                          "freed_bytes": sum(e["bytes"] for e in removed)}, indent=2))
        return 0
    verb = "WOULD DELETE" if a.dry_run else "deleted"
    print(f"clean-runs: {runs} — {len(entries)} run dir(s), "
          f"{human_bytes(sum(e['bytes'] for e in entries))}, AGE={a.age:g} h")
    for e in entries:
        mark = verb if e["delete"] else "kept"
        print(f"  {mark:12s} {e['name']:44s} {human_bytes(e['bytes']):>9s}  {e['why']}")
    for why in refused:
        print(f"  spared      {why}")
    freed = sum(e["bytes"] for e in removed)
    print(f"{len(removed)} dir(s) {'reclaimable' if a.dry_run else 'removed'} "
          f"({human_bytes(freed)}); {len(kept)} kept "
          f"({human_bytes(sum(e['bytes'] for e in kept))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
