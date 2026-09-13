"""The BRIDGE lane: deck text in, a result directory out; `make doctor` proves it with one resistor.

**Selected by `lane: bridge` in `harness.yaml`.** The default is the open lane
(`design/sim_ngspice.py`), and a design that never writes the key never loads this module.

A commercial kit's models load only in the vendor simulator, and that simulator lives on the lab's
shared EDA server — so this lane is REMOTE: the deck goes up through the lab's bridge, runs there,
and the result directory plus the tool log come back into a per-run work directory. Kit bytes never
reach the workstation or the model.

**Every reusable part of that is the platform's bridge-lane package**, whose distribution name is
`spicexplorer-` plus the simulator's name (`pyproject.toml` says how a commercial-PDK design adds
it; do NOT name the bridge itself — the platform pins it). It owns the per-run directory
`<label>-<deck hash>`, the `.busy` marker with dead-owner reclaim, the success rule (remote exit 0
AND a non-empty result directory), result parsing, and redaction of kit-shaped paths out of any log
tail before it reaches an exception — those end up in ledger rows and PR bodies. A bug in any of
that is fixed once, in the platform, for every design; this file must never grow a private driver.

What stays HERE is this repo's policy, in the shape the rest of the repo (`design.metrics`, the
ledger, `make doctor`) already expects from the open lane:

* **WHERE** runs go — `work()`: `$<work_env>`, else `$SX_SCRATCH/<design>-<checkout>`; never the
  repo, never `/tmp` (parallel jobs share it), never a path carrying a tool's name.
* **WHICH** simulator — `simulator()`: `$<sim_env>` when it names a launcher that already carries
  the tool environment; unset means the platform lane's own plain command name, which the bridge
  resolves ON THE SERVER (a local absolute path would be meaningless there).
* **WHICH MODE** — `MODE`, the one argument shape this design's benches run under.
* **WHAT the doctor expects** — `preflight()` runs the probe through THIS wrapper (this work root,
  this timeout), so `make doctor` proves the lane the benches use rather than a default one.

**WHICH kit a deck includes is not here: it is `design/pdk.py`.** Decks are built naming a TOKEN
rather than a path, and `run()` substitutes the real one in as it hands the deck over — so no kit
path is committed anywhere in this repo and the frozen reference decks stay portable, byte for
byte. `pdk` is imported inside `run()` because `pdk` imports this module for `H`.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from spicexplorer_harness import load
from spicexplorer_spectre import doctor as _doctor
from spicexplorer_spectre import lane as _lane
from spicexplorer_spectre import results as _results
from spicexplorer_spectre.lane import LaneNotConfigured, Run, SimError
from spicexplorer_spectre.results import psf, psf_dir, scalars, wall_time

H = load(Path(__file__).resolve().parents[1])
REPO = H.root
CHECKOUT = hashlib.sha256(str(REPO).encode()).hexdigest()[:8]

LANE_ENV = H.sim_env      # a launcher carrying the tool environment; unset = the lane's own name
WORK_ENV = H.work_env     # the work root; else $SX_SCRATCH/<design>-<checkout>
DECK_NAME = _lane.DECK_NAME   # the deck every run dir holds, under the name the tool's logs quote

# The mode args every bench in this design runs under, as the platform lane's `mode_args` spells
# them. `""` — the default here — passes no mode flags, so the simulator runs in its own default
# engine, which is the conservative choice. A mode that trades accuracy for speed is a decision
# about the numbers this repo certifies, so it is stated ONCE, here, and never per bench.
MODE = ""

# The probe and its keys are the platform lane's: the bridge names a scalar
# `"<analysis>_<instance>:<parameter>"` — THE ANALYSIS NAME IS PART OF THE KEY, which is also why a
# commercial-PDK design's `metrics.KEYMAP` is keyed on (bench, measure).
PROBE = _doctor.PROBE
PROBE_KEYS = _doctor.PROBE_KEYS

__all__ = ["H", "REPO", "CHECKOUT", "LANE_ENV", "WORK_ENV", "DECK_NAME", "MODE", "PROBE",
           "PROBE_KEYS", "LaneNotConfigured", "SimError", "Run", "work", "simulator", "run",
           "psf", "psf_dir", "scalars", "wall_time", "preflight", "main"]


# ------------------------------------------------------------------ where and what ----

def work() -> Path:
    """`$<work_env>`, else `$SX_SCRATCH/<design>-<checkout>` (else `~/sx-scratch/...`).

    The platform lane's `work_root` enforces the rule rather than trusting it: never the repo,
    never `/tmp` (parallel jobs share it), never a tool-named path.
    """
    return _lane.work_root(H.name, env=WORK_ENV, checkout=CHECKOUT, repo=REPO)


def simulator() -> str:
    """`$<sim_env>` if it is set, else `""` — meaning "the platform lane's own command name".

    Returned empty rather than defaulted here on purpose: the name of the binary belongs to the
    lane package, which resolves it on the REMOTE host after sourcing the tool environment there.
    Repeating it in every design is how one rename turns into N edits.
    """
    return (os.environ.get(LANE_ENV) or "").strip()


def mode_args() -> list[str]:
    """`MODE` as the lane's argument list; `MODE = ""` is no mode flags at all."""
    return _lane.mode_args(MODE) if MODE else []


# the private helpers a design's own tests tend to pin — the platform lane's, never re-implemented
_slug = _lane.slug
_deck_hash = _lane.deck_hash
_redact = _lane.redact
_tail = _lane.tail
_host = _lane.host
_psf_dirs = _results.psf_dirs


# ------------------------------------------------------------------ run ---------------

def run(deck: str, label: str, *, timeout: int = 3600, extra_files: dict[str, str] | None = None,
        include_files: list[str] | None = None, spectre_args: list[str] | None = None) -> Run:
    """Simulate `deck` in `work()/runs/<label>-<deck hash>/` on the remote lane.

    `extra_files` are written beside the deck (a side file the deck `include`s, a stimulus file);
    `include_files` names files the bridge must stage remotely (a behavioural model, a model card).
    Prefer RELATIVE `include` lines: the bridge uploads by basename and does not rewrite paths
    inside the deck body, so a local absolute include ships verbatim and then fails to resolve.

    THE ONE PLACE the model-library path enters a deck. Decks are built as portable text naming
    `pdk.TOKEN` — so they can be committed, hashed, diffed and rebuilt byte for byte — and it is
    resolved here, against this machine, at the moment of handing the deck over. The kit's
    resolved include is absolute on purpose: that path exists on the simulation host and nowhere
    else.

    Raises `SimError` when the lane reports anything but success, or when the run came back with
    neither a result nor a scalar (the emptiness rule: a deck whose analyses never ran can still
    exit 0); `LaneNotConfigured` when this machine has no bridge profile.
    """
    if not _slug(label.strip()):
        raise ValueError("run label must not be empty")
    from . import pdk

    args = mode_args() if spectre_args is None else list(spectre_args)
    binary = simulator()
    named = {"simulator": binary} if binary else {}
    return _lane.run_deck(pdk.restore(deck), label, work=work(), timeout=timeout,
                          extra_files=extra_files, include_files=include_files,
                          spectre_args=args, **named)


# ------------------------------------------------------------------ doctor ------------

def preflight(deck: str = PROBE,
              expect: tuple[tuple[str, ...], float, float] = (PROBE_KEYS, 1.0, 1e-3)) -> dict:
    """Simulate `deck` and check `expect` = (candidate scalar keys, |value| in mA, tol).

    Reports rather than raises, and on a key miss the platform doctor lists the scalars the run DID
    return, so the first live run on a new tool version is self-diagnosing instead of a bare
    mismatch.

    An unresolved process is reported BEFORE anything is simulated. The probe is one resistor and
    would pass without the kit, but a lane that cannot bind this design to its model library is not
    alive however well the probe simulates — the same rule the open lane applies to an unset
    `DECK_VARS`. Neither message names the value, only the variables that supply it.
    """
    info: dict = {"lane": "remote commercial simulator through the lab's bridge",
                  "simulator": simulator() or "(the lane's own name, resolved on the server)",
                  "mode": MODE, "work": "", "ok": False, "note": "", "scalars": []}
    try:
        info["work"] = str(work())
    except ValueError as exc:
        info["note"] = str(exc)
        return info
    from . import pdk

    blocked = pdk.unresolved()
    if blocked:
        info["note"] = blocked
        return info
    rep = _doctor.preflight(work=work(), run=lambda d, label: run(d, label, timeout=300),
                            deck=deck, expect=expect)
    info.update({k: rep[k] for k in ("ok", "note", "scalars", "psf", "wall_s", "not_configured")
                 if k in rep})
    return info


def main() -> int:
    """`make doctor` (`python -m design.sim`, dispatched here by `design/sim.py`)."""
    rep = preflight()
    print(json.dumps(rep, indent=2, default=str))
    if rep.get("not_configured"):
        print("lane not configured: no bridge profile on this machine, or no bridge in this "
              "interpreter (uv sync). Not a stop — everything that does not need the simulator "
              "still runs.", file=sys.stderr)
        return 2
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
