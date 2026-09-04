"""The simulator lane: deck text in, run directory out; `make doctor` proves it with one resistor.

Native ngspice through a thin subprocess path: the platform's `NGSpice_Wrapper` is file-centric
(wipes its output folder, no per-run cwd/`.spiceinit`), which is the platform gap this module
fills until a deck-string `run(deck, label, workdir, spiceinit)` lands beside it. Every run gets
`work()/runs/<label>/` with its own `.spiceinit` (the PDK's `$SPICE_USERINIT_DIR/.spiceinit`
plus `spiceinit_extra`), `deck.sp`, `ngspice.out`, `wall.txt` and rawfile(s). ngspice exits 0
after a failed operating point and leaves a rawfile full of zeros, so the log is scanned for
fatal lines before anything is trusted, and `print`/`meas` scalars come back parsed from it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from spicexplorer_harness import load
from spicexplorer_harness.ledger import deck_hash  # noqa: F401 - re-exported for callers
from spicexplorer_waveview.logs import classify_line

H = load(Path(__file__).resolve().parents[1])
REPO = H.root
CHECKOUT = hashlib.sha256(str(REPO).encode()).hexdigest()[:8]

# Env-var convention of the LDO/TX/LPF repos: `exp_env: LDO_EXP` => `LDO_NGSPICE`, `LDO_WORK`.
_PREFIX = H.exp_env[:-4] if H.exp_env.endswith("_EXP") else "SIM"
LANE_ENV = f"{_PREFIX}_NGSPICE"   # the native binary; else `ngspice` on PATH, else ~/local/bin/ngspice
WORK_ENV = f"{_PREFIX}_WORK"      # the work root; else $SX_SCRATCH/<design>-<checkout>

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


class SimError(RuntimeError):
    """ngspice logged a fatal line, or produced neither a rawfile nor a scalar."""


@dataclasses.dataclass
class Run:
    """One finished run; `os.fspath(run)` is its directory, so `Path(run) / "x"` works."""

    label: str
    dir: Path
    deck: Path
    log: Path
    raws: list[Path]
    wall: float
    measures: dict[str, float]
    failed: list[str]           # `meas` names ngspice reported as failed

    @property
    def raw(self) -> Path | None:
        return self.raws[0] if self.raws else None

    def __fspath__(self) -> str:
        return str(self.dir)

    def text(self) -> str:
        return self.log.read_text(errors="replace")


# ------------------------------------------------------------------ where and what ----

def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)


def work() -> Path:
    """`$<PREFIX>_WORK`, else `$SX_SCRATCH/<design>-<checkout>` (else `~/sx-scratch/...`); never the repo."""
    if os.environ.get(WORK_ENV):
        return Path(os.environ[WORK_ENV])
    scratch = Path(os.environ.get("SX_SCRATCH") or Path.home() / "sx-scratch")
    return scratch / f"{_slug(H.name).strip('_') or 'design'}-{CHECKOUT}"


def ngspice() -> str:
    for cand in (os.environ.get(LANE_ENV), shutil.which("ngspice"),
                 str(Path.home() / "local" / "bin" / "ngspice")):
        if cand and Path(cand).is_file():
            return cand
    raise FileNotFoundError(f"no ngspice binary: set {LANE_ENV} or put ngspice on PATH")


def userinit_dir() -> Path | None:
    d = os.environ.get("SPICE_USERINIT_DIR")
    return Path(d) if d else None


def spiceinit(extra: str = "") -> str:
    """The per-run init file: `$SPICE_USERINIT_DIR/.spiceinit` (else `~/.spiceinit`), then `extra` lines."""
    base = ""
    for d in (userinit_dir(), Path.home()):
        if d and (d / ".spiceinit").is_file():
            base = (d / ".spiceinit").read_text()
            break
    return base.rstrip("\n") + "\n" + (extra.rstrip("\n") + "\n" if extra else "")


def _env() -> dict[str, str]:
    """The PDK init file spells paths as `$PDK_ROOT/$PDK`; default both from SPICE_USERINIT_DIR."""
    env = dict(os.environ)
    d = userinit_dir()
    if d and len(d.parents) >= 3:   # <PDK_ROOT>/<PDK>/libs.tech/ngspice
        env.setdefault("PDK", d.parents[1].name)
        env.setdefault("PDK_ROOT", str(d.parents[2]))
    return env


# ------------------------------------------------------------------ the log -----------

# ngspice reports these without a non-zero exit and without an `Error:` prefix.
_FATAL = ("doAnalyses: iteration limit reached", "Transient solution failed", "timestep too small",
          "singular matrix", "Unknown model type", "could not find a valid modelname",
          "Error on line", "simulation interrupted")
_MEASURE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-+]?[0-9.]+(?:[eE][-+]?[0-9]+)?)"
                      r"(?:\s+(?:at|from|to)\s*=.*)?\s*$")
_FAILED = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*failed", re.IGNORECASE)


def fatal_lines(log: str) -> list[str]:
    """Lines that make a run a failure whatever the rawfile says (waveview's `error` level + `_FATAL`)."""
    return [ln for ln in log.splitlines()
            if classify_line(ln) == "error" or any(f.lower() in ln.lower() for f in _FATAL)]


def parse_measures(log: str) -> tuple[dict[str, float], list[str]]:
    """(scalars, failed `meas` names) from a batch log -- the analog-db tier's regexes (platform gap: belong in `spicexplorer_waveview.logs`)."""
    measures: dict[str, float] = {}
    failed: list[str] = []
    for line in log.splitlines():
        m = _MEASURE.match(line)
        if m:
            measures[m.group(1).lower()] = float(m.group(2))
        elif (f := _FAILED.match(line)):
            failed.append(f.group(1).lower())
    return measures, failed


def _tail(s: str, n: int = 30) -> str:
    return "\n".join([ln for ln in s.splitlines() if ln.strip()][-n:])


# ------------------------------------------------------------------ run ---------------

def run(deck: str, label: str, *, timeout: int = 3600, extra_files: dict[str, str] | None = None,
        spiceinit_extra: str = "") -> Run:
    """Simulate `deck` (its own `.control`: `write <x>.raw` and/or `print`/`meas`) in `work()/runs/<label>/`."""
    label = _slug(label)
    rd = work() / "runs" / label
    rd.mkdir(parents=True, exist_ok=True)
    for stale in rd.glob("*.raw"):
        stale.unlink()
    (rd / ".spiceinit").write_text(spiceinit(spiceinit_extra))
    (rd / "deck.sp").write_text(deck)
    for name, text in (extra_files or {}).items():
        (rd / name).write_text(text)
    cmd = [ngspice(), "-b", "deck.sp"]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=rd, env=_env(), capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise SimError(f"{label}: ngspice timed out after {timeout} s ({rd})") from None
    wall = time.perf_counter() - t0
    log = proc.stdout + "\n---- stderr ----\n" + proc.stderr
    (rd / "ngspice.out").write_text(log)
    (rd / "wall.txt").write_text(f"{wall:.3f}\n")
    measures, failed = parse_measures(proc.stdout)
    r = Run(label, rd, rd / "deck.sp", rd / "ngspice.out", sorted(rd.glob("*.raw")), wall,
            measures, failed)
    bad = fatal_lines(log)
    if bad:
        raise SimError(f"{label}: simulator error ({rd})\n  " + "\n  ".join(bad[:8]))
    if not r.raws and not measures and not failed:
        raise SimError(f"{label}: rc={proc.returncode}, no rawfile and no scalar ({rd})\n{_tail(log)}")
    return r


def _raw_path(run: Run | Path, name: str) -> Path:
    p = Path(run) / name
    if not p.exists():
        found = sorted(Path(run).glob("*.raw"))
        if not found:
            raise SimError(f"no rawfile in {Path(run)}")
        p = found[0]
    return p


def raw(run: Run | Path, name: str = "sim.raw"):
    """The rawfile as `spicelib.RawRead` (`.get_trace("v(out)").get_wave()`); `name`, else the first `*.raw`."""
    from spicelib import RawRead

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
    info = {"lane": "native ngspice", "ngspice": "", "work": str(work()),
            "userinit": str(userinit_dir() or ""), "ok": False, "note": ""}
    try:
        info["ngspice"] = ngspice()
        r = run(deck, "_preflight", timeout=120, spiceinit_extra="echo LANE_INIT_OK")
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
