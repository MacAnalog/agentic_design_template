"""The simulator lane: deck text in, run directory out; `make doctor` proves it with one resistor.

A thin wrapper over the platform's `spicexplorer_core.spice_engine.run_deck` (the deck-string
ngspice lane: per-run directory `<label>-<deck hash>`, per-run `.spiceinit` in the cwd, `.busy`
marker with dead-owner reclaim, rc check, `print`/`meas` scalars and failed `.meas` names parsed
from the log, fatal lines raised). What stays here is this repo's policy: WHERE runs go
(`work()`: `$<work_env>`, else `$SX_SCRATCH/<design>-<checkout>/runs`), WHICH binary
(`ngspice()`: `$<sim_env>`, else PATH), WHAT the per-run init file says (`spiceinit()`: the PDK's
`$SPICE_USERINIT_DIR/.spiceinit` plus `SPICEINIT_EXTRA`), the `PDK`/`PDK_ROOT` defaults the init
file expands, the "no rawfile and no scalar is a failure" rule, and the doctor probe. The env-var
names come from `harness.yaml` (`sim_env`, `work_env`; defaulted from `exp_env` by the prefix rule).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from spicexplorer_core.spice_engine import DeckRunError, RunResult, run_deck
from spicexplorer_core.spice_engine.deck_run import slug as _slug
from spicexplorer_core.spice_engine.sim_log import fatal_lines, parse_measures
from spicexplorer_harness import load

H = load(Path(__file__).resolve().parents[1])
REPO = H.root
CHECKOUT = hashlib.sha256(str(REPO).encode()).hexdigest()[:8]

LANE_ENV = H.sim_env      # the native binary; else `ngspice` on PATH
WORK_ENV = H.work_env     # the work root; else $SX_SCRATCH/<design>-<checkout>
SPICEINIT_EXTRA = ""      # lines every run appends to the PDK init (a compatibility `set`, an `osdi` load)

# Machine-specific paths a deck must NOT carry, named in the deck text as `$NAME` and resolved by
# `run()` (see `resolve()`), e.g. `("PDK_LIB",)` for a model library installed only on the machines
# licensed to hold it. Empty here: the open lane's model paths come from the PDK's `.spiceinit`.
DECK_VARS: tuple[str, ...] = ()

# A short tag for THIS design, e.g. `"DN006"`. When set, `resolve()` reads `<SCOPE>_<NAME>` before
# the bare `<NAME>`, and that is the variable a person should export. The bare name is shared: it is
# the text inside every frozen deck, and a name chosen from the env prefix is not unique either
# (two designs in this lab's directory share `OTA_`), so ONE export in ONE shell profile can feed
# two repos pinned to different library revisions. A scoped export reaches this design only.
DECK_VAR_SCOPE: str = ""

# What each variable's value must CONTAIN — usually the model-library revision name that
# `doc/environment.md` pins, e.g. `{"PDK_LIB": "crn65gplus_2d5_lk_v1d0"}`. The revision is the one
# input to reproducing a certified scorecard that a design deliberately does not commit, so a value
# that does not carry it is refused: an unchecked export otherwise produces a full green `make check`
# against a different process, recorded nowhere but the shell that ran it. A deliberate
# cross-revision run is still possible — it has to be typed (`<NAME>_ALLOW_MISMATCH=1`), so it is
# visible in that shell and in any recorded command.
DECK_VAR_PINS: dict[str, str] = {}

PROBE = """* lane preflight: one resistor
v1 a 0 1
r1 a 0 1k
.control
op
let i_ma = -i(v1)*1e3
print i_ma
write sim.raw
quit
.endc
.end
"""

# Platform names, kept under the names this repo's tests, docs and ledger rows use.
SimError = DeckRunError
Run = RunResult
__all__ = ["H", "REPO", "CHECKOUT", "LANE_ENV", "WORK_ENV", "SPICEINIT_EXTRA", "DECK_VARS",
           "DECK_VAR_SCOPE", "DECK_VAR_PINS", "DeckVarError", "PROBE",
           "SimError", "Run", "work", "ngspice", "userinit_dir", "spiceinit", "resolve",
           "deck_var_names",
           "fatal_lines", "parse_measures", "run", "raw", "dataset", "wall_time", "preflight"]


# ------------------------------------------------------------------ where and what ----

def work() -> Path:
    """`$<work_env>`, else `$SX_SCRATCH/<design>-<checkout>` (else `~/sx-scratch/...`); never the repo, never /tmp."""
    if os.environ.get(WORK_ENV):
        w = Path(os.environ[WORK_ENV])
    else:
        scratch = Path(os.environ.get("SX_SCRATCH") or Path.home() / "sx-scratch")
        w = scratch / f"{_slug(H.name).strip('_') or 'design'}-{CHECKOUT}"
    if str(w.resolve()).startswith("/tmp/") or w.resolve() == REPO or REPO in w.resolve().parents:
        raise ValueError(f"work root {w} is under /tmp or inside the repo; set {WORK_ENV} or SX_SCRATCH")
    return w


def ngspice() -> str:
    for cand in (os.environ.get(LANE_ENV), shutil.which("ngspice")):
        if cand and Path(cand).is_file():
            return cand
    raise FileNotFoundError(f"no ngspice binary: set {LANE_ENV} or put ngspice on PATH")


def userinit_dir() -> Path | None:
    d = os.environ.get("SPICE_USERINIT_DIR")
    return Path(d) if d else None


def spiceinit(extra: str = "") -> str:
    """The per-run init file: `$SPICE_USERINIT_DIR/.spiceinit` (required: the PDK's models/OSDI), then `extra` lines."""
    d = userinit_dir()
    if d is None or not (d / ".spiceinit").is_file():
        raise FileNotFoundError("SPICE_USERINIT_DIR must point at the PDK's ngspice dir holding .spiceinit")
    base = (d / ".spiceinit").read_text().strip()
    if not base:
        raise FileNotFoundError(f"{d / '.spiceinit'} is empty")
    return base + "\n" + (extra.strip() + "\n" if extra.strip() else "")


def _env() -> dict[str, str]:
    """The PDK init file spells paths as `$PDK_ROOT/$PDK`; default both from SPICE_USERINIT_DIR."""
    env = dict(os.environ)
    d = userinit_dir()
    if d and len(d.parents) >= 3:   # <PDK_ROOT>/<PDK>/libs.tech/ngspice
        env.setdefault("PDK", d.parents[1].name)
        env.setdefault("PDK_ROOT", str(d.parents[2]))
    return env


def _tail(s: str, n: int = 30) -> str:
    return "\n".join([ln for ln in s.splitlines() if ln.strip()][-n:])


# ------------------------------------------------------------------ portable decks ----

class DeckVarError(RuntimeError):
    """A deck variable is set, but to a value this design may not silently simulate against."""


def deck_var_names(name: str) -> tuple[str, ...]:
    """The environment variables `resolve()` reads for one deck name, in order.

    The design-scoped name first (`DECK_VAR_SCOPE`), then the bare name the deck text carries. Two
    names rather than a rename, because the bare one IS the text inside every already-frozen deck:
    renaming it would force a re-certify of every reference.
    """
    scoped = f"{DECK_VAR_SCOPE}_{name}" if DECK_VAR_SCOPE and not name.startswith(
        f"{DECK_VAR_SCOPE}_") else ""
    return (scoped, name) if scoped else (name,)


def resolve(deck: str) -> str:
    """`$NAME` -> the environment value, for the names declared in `DECK_VARS` and no others.

    A deck is a DOCUMENT before it is a simulator input: `--certify` writes it into the frozen dir,
    `make freeze` sha-locks it, `git diff` reads it, and the `deck-rebuild` lint rebuilds it byte
    for byte. A path that exists only on some machines — a site-licensed model library, a shared
    model root — therefore may never be written into deck text: the deck names the variable, this
    function substitutes the value in the last moment before the simulator sees it, and every
    other consumer keeps seeing portable text. Redaction on write with restoration on read is NOT
    an alternative: the rebuild lint compares bytes and every redacted bench fails to reproduce.

    Declared names only, never `os.path.expandvars`: `$` opens a comment in some netlist dialects,
    so a blanket expansion silently rewrites lines this repo never meant to touch.

    Two rules beyond substitution, both paid for elsewhere
    (MacAnalog/macanalog-design-directory#38): the DESIGN-SCOPED variable is read first, because a
    shared name means one export can feed two repos; and a value declared in `DECK_VAR_PINS` must
    carry its pin, on every route rather than on a fallback nobody uses. Neither message ever
    echoes the value — a machine-specific path is not printed, only the variable that supplies it.
    """
    for name in DECK_VARS:
        token = f"${name}"
        if token not in deck:
            continue
        names = deck_var_names(name)
        used, value = "", ""
        for candidate in names:                       # every candidate is tried before failing
            value = (os.environ.get(candidate) or "").strip()
            if value:
                used = candidate
                break
        if not used:
            raise FileNotFoundError(
                f"the deck names {token} but {' / '.join(names)} "
                f"{'are' if len(names) > 1 else 'is'} unset — export it to the path it stands "
                f"for (per machine, never committed; `doc/environment.md` pins WHICH library by "
                f"revision name, and `design.sim.DECK_VARS` declares the variable)")
        pin = DECK_VAR_PINS.get(name, "")
        if pin and pin not in value and not any(
                os.environ.get(f"{n}_ALLOW_MISMATCH") for n in names):
            raise DeckVarError(
                f"{used} points at something that does not carry this design's pin ({pin}). "
                f"Re-pin `design.sim.DECK_VAR_PINS` and doc/environment.md together, or set "
                f"{used}_ALLOW_MISMATCH=1 for a deliberate one-off — a silent change of model "
                f"library invalidates every certified number.")
        deck = deck.replace(token, value)
    return deck


# ------------------------------------------------------------------ run ---------------

def run(deck: str, label: str, *, timeout: int = 3600, extra_files: dict[str, str] | None = None,
        spiceinit_extra: str | None = None) -> Run:
    """Simulate `deck` (its own `.control`: `write <x>.raw` and/or `print`/`meas`) in `work()/runs/<label>-<hash>/`.

    THE one place a machine-specific path enters a deck: `resolve()` runs here and nowhere else,
    so what is built, logged, frozen and diffed stays portable.
    """
    if not _slug(label.strip()):
        raise ValueError("run label must not be empty")
    extra = SPICEINIT_EXTRA if spiceinit_extra is None else spiceinit_extra
    r = run_deck(resolve(deck), label=label, workdir=work() / "runs", spiceinit=spiceinit(extra),
                 ngspice=ngspice(), timeout=timeout, extra_files=extra_files, env=_env())
    if not r.raws and not r.measures and not r.failed:
        raise SimError(f"{r.dir.name}: no rawfile and no scalar\n{_tail(r.text())}", r)
    return r


def _raw_path(run: Run | Path, name: str) -> Path:
    p = Path(run) / name
    if not p.exists():
        found = sorted(Path(run).glob("*.raw"))
        if not found:
            raise SimError(f"no rawfile in {Path(run).name}")
        p = found[0]
    return p


def raw(run: Run | Path, name: str = "sim.raw"):
    """The rawfile as `spicelib.RawRead` (`.get_trace("v(out)").get_wave()`); `name`, else the first `*.raw`."""
    from spicexplorer_core.spice_engine.spicelib import RawRead

    return RawRead(str(_raw_path(run, name)))


def dataset(run: Run | Path, name: str = "sim.raw"):
    """The rawfile as a waveview `WaveDataset`, so registry recipes run on it (`spicexplorer_waveview.measure.measure_dataset`)."""
    from spicexplorer_waveview.loaders import load_result

    log = Path(run) / "ngspice.out"
    return load_result(_raw_path(run, name), engine="ngspice", log_path=log if log.exists() else None)


def wall_time(run: Run | Path) -> float:
    try:
        return float((Path(run) / "wall.txt").read_text())
    except (OSError, ValueError):
        return float("nan")


# ------------------------------------------------------------------ doctor ------------

def preflight(deck: str = PROBE, expect: tuple[str, float, float] = ("i_ma", 1.0, 1e-6)) -> dict:
    """Simulate `deck` and check `expect` = (scalar, value, tol); a design passes its own PDK-device probe."""
    info = {"lane": "native ngspice", "ngspice": "", "userinit": str(userinit_dir() or ""),
            "work": "", "ok": False, "note": "", "deck_vars": list(DECK_VARS)}
    unset = [n for n in DECK_VARS
             if not any((os.environ.get(c) or "").strip() for c in deck_var_names(n))]
    if unset:
        # a declared variable is what every real bench's deck names; a lane that cannot resolve it
        # is not alive, however well the probe simulates
        info["note"] = f"deck vars unset: {unset} — export them (design.sim.DECK_VARS)"
        return info
    try:
        info["work"] = str(work())
        info["ngspice"] = ngspice()
        r = run(deck, "_preflight", timeout=120,
                spiceinit_extra=f"{SPICEINIT_EXTRA}\necho LANE_INIT_OK")
        key, want, tol = expect
        got = r.measures.get(key, float("nan"))
        init_ok = "LANE_INIT_OK" in r.text()
        info["ok"] = bool(abs(got - want) <= tol and r.raw is not None and init_ok)
        info["note"] = (f"{key}={got:g} (want {want:g}); raw={r.raw}; per-run .spiceinit "
                        f"{'read' if init_ok else 'NOT read'}; {r.wall:.2f} s")
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        info["note"] = str(exc)[:600]
    return info


if __name__ == "__main__":  # `make doctor`
    r = preflight()
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["ok"] else 1)
