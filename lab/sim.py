"""The simulator lane: deck text in, run directory out; `make doctor` proves it with one resistor.

Native ngspice through a thin subprocess path: the platform's `NGSpice_Wrapper` is file-centric
(wipes its output folder, no per-run cwd/`.spiceinit`), which is the platform gap this module
fills until a deck-string `run(deck, label, workdir, spiceinit)` lands beside it. Every run gets
`work()/runs/<label>-<deck hash>/` with its own `.spiceinit` (the PDK's
`$SPICE_USERINIT_DIR/.spiceinit` plus `SPICEINIT_EXTRA`), `deck.sp`, `ngspice.out`, `wall.txt`
and rawfile(s). ngspice exits 0 after a failed operating point, an ignored device line or a
failed `.meas`, so the log is scanned before anything is trusted: fatal lines raise `SimError`,
a failed `.meas` lands in `Run.failed`, and `print`/`meas` scalars come back parsed from the log.
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
from spicexplorer_harness.ledger import deck_hash
from spicexplorer_waveview.logs import classify_line

H = load(Path(__file__).resolve().parents[1])
REPO = H.root
CHECKOUT = hashlib.sha256(str(REPO).encode()).hexdigest()[:8]

# `exp_env: FOO_EXP` in harness.yaml names FOO_NGSPICE and FOO_WORK; no prefix => SIM_*.
_PREFIX = H.exp_env[:-4] if H.exp_env.endswith("_EXP") and len(H.exp_env) > 4 else "SIM"
LANE_ENV = f"{_PREFIX}_NGSPICE"   # the native binary; else `ngspice` on PATH
WORK_ENV = f"{_PREFIX}_WORK"      # the work root; else $SX_SCRATCH/<design>-<checkout>
SPICEINIT_EXTRA = ""              # lines every run appends to the PDK init (a compatibility `set`, an `osdi` load)

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
    """ngspice exited non-zero, logged a fatal line, or produced neither a rawfile nor a scalar."""


@dataclasses.dataclass
class Run:
    """One finished run; `os.fspath(run)` / `str(run)` is its directory, so `Path(run) / "x"` works."""

    label: str
    dir: Path
    deck: Path
    log: Path
    raws: list[Path]
    wall: float
    rc: int
    measures: dict[str, float]
    failed: list[str]           # `.meas` names ngspice reported as failed

    @property
    def raw(self) -> Path | None:
        return self.raws[0] if self.raws else None

    def __fspath__(self) -> str:
        return str(self.dir)

    def __str__(self) -> str:
        return str(self.dir)

    def text(self) -> str:
        return self.log.read_text(errors="replace")


# ------------------------------------------------------------------ where and what ----

def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)


def work() -> Path:
    """`$<PREFIX>_WORK`, else `$SX_SCRATCH/<design>-<checkout>` (else `~/sx-scratch/...`); never the repo, never /tmp."""
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


# ------------------------------------------------------------------ the log -----------

# Bare lines ngspice prints for failures it does not exit non-zero on (no `Error:` prefix).
_FATAL = ("doAnalyses: iteration limit reached", "Transient solution failed", "timestep too small",
          "Unknown model type", "could not find a valid modelname", "Error on line",
          "simulation interrupted")
# `Warning:` lines that hide a silently wrong deck (a device line dropped => zeros in the rawfile).
_FATAL_WARNINGS = ("ignored!", "is not a valid")
# `Error:` lines that are NOT fatal: a failed `.meas` (reported by name in `Run.failed`).
_ERROR_OK = re.compile(r"Error:\s+measure\b", re.IGNORECASE)
_MEASURE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-+]?[0-9.]+(?:[eE][-+]?[0-9]+)?)"
                      r"(?:\s+(?:at|from|to)\s*=.*)?\s*$")
_FAILED = re.compile(r"^\s*\.?meas\s+\w+\s+([A-Za-z_][A-Za-z0-9_]*)\b.*\bfailed!?\s*$", re.IGNORECASE)


def fatal_lines(log: str) -> list[str]:
    """Lines that make a run a failure whatever the rawfile says: waveview's `error` level (except a failed `.meas`), the `_FATAL` strings, and warnings that dropped a device line; other warnings are recoverable."""
    out = []
    for ln in log.splitlines():
        level = classify_line(ln)
        if level == "warning":
            if any(w in ln for w in _FATAL_WARNINGS):
                out.append(ln)
        elif level == "error":
            if not _ERROR_OK.search(ln):
                out.append(ln)
        elif any(f.lower() in ln.lower() for f in _FATAL):
            out.append(ln)
    return out


def parse_measures(log: str) -> tuple[dict[str, float], list[str]]:
    """(scalars, failed `.meas` names) from a batch log; the scalar regex is the analog-db tier's (platform gap: belongs in `spicexplorer_waveview.logs`)."""
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
        spiceinit_extra: str | None = None) -> Run:
    """Simulate `deck` (its own `.control`: `write <x>.raw` and/or `print`/`meas`) in `work()/runs/<label>-<hash>/`."""
    label = _slug(label.strip())
    if not label:
        raise ValueError("run label must not be empty")
    root = work()
    rd = root / "runs" / f"{label}-{deck_hash(deck)[:8]}"
    rel = rd.relative_to(root)
    rd.mkdir(parents=True, exist_ok=True)
    busy = rd / ".busy"          # holds the owner's PID; a dead owner's marker is reclaimed
    _claim(busy, label, rel)
    try:
        for stale in rd.glob("*.raw"):
            stale.unlink()
        extra = SPICEINIT_EXTRA if spiceinit_extra is None else spiceinit_extra
        (rd / ".spiceinit").write_text(spiceinit(extra))
        (rd / "deck.sp").write_text(deck)
        for name, text in (extra_files or {}).items():
            (rd / name).write_text(text)
        cmd = [ngspice(), "-b", "deck.sp"]
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(cmd, cwd=rd, env=_env(), capture_output=True, text=True,
                                  timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise SimError(f"{label}: ngspice timed out after {timeout} s ({rel})") from None
        wall = time.perf_counter() - t0
        log = proc.stdout + "\n---- stderr ----\n" + proc.stderr
        (rd / "ngspice.out").write_text(log)
        (rd / "wall.txt").write_text(f"{wall:.3f}\n")
    finally:
        busy.unlink(missing_ok=True)
    measures, failed = parse_measures(proc.stdout)
    r = Run(label, rd, rd / "deck.sp", rd / "ngspice.out", sorted(rd.glob("*.raw")), wall,
            proc.returncode, measures, failed)
    bad = fatal_lines(log)
    if bad:
        raise SimError(f"{label}: simulator error ({rel})\n  " + "\n  ".join(bad[:8]))
    if proc.returncode != 0:
        raise SimError(f"{label}: ngspice exited rc={proc.returncode} ({rel})\n{_tail(log)}")
    if not r.raws and not measures and not failed:
        raise SimError(f"{label}: no rawfile and no scalar ({rel})\n{_tail(log)}")
    return r


def _claim(busy: Path, label: str, rel: Path) -> None:
    for attempt in (0, 1):
        try:
            fd = os.open(busy, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return
        except FileExistsError:
            try:
                os.kill(int(busy.read_text().strip() or 0), 0)
                alive = True
            except (ProcessLookupError, ValueError, OSError):
                alive = False
            if alive or attempt:
                raise SimError(f"{label}: {rel} is busy (another run of the same deck is in progress)") from None
            busy.unlink(missing_ok=True)


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
