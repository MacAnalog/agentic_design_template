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
__all__ = ["H", "REPO", "CHECKOUT", "LANE_ENV", "WORK_ENV", "SPICEINIT_EXTRA", "PROBE", "SimError",
           "Run", "work", "ngspice", "userinit_dir", "spiceinit", "fatal_lines", "parse_measures",
           "run", "raw", "dataset", "wall_time", "preflight"]


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


# ------------------------------------------------------------------ run ---------------

def run(deck: str, label: str, *, timeout: int = 3600, extra_files: dict[str, str] | None = None,
        spiceinit_extra: str | None = None) -> Run:
    """Simulate `deck` (its own `.control`: `write <x>.raw` and/or `print`/`meas`) in `work()/runs/<label>-<hash>/`."""
    if not _slug(label.strip()):
        raise ValueError("run label must not be empty")
    extra = SPICEINIT_EXTRA if spiceinit_extra is None else spiceinit_extra
    r = run_deck(deck, label=label, workdir=work() / "runs", spiceinit=spiceinit(extra),
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
            "work": "", "ok": False, "note": ""}
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
