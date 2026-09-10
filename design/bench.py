"""One bench's raw result -> the numbers the scorecard is written in. THE single reduction.

**A reduction that lives in an experiment cannot be certified.** `metrics.measure()` reads a deck's
own printed scalars, which is right for a bench that `print`s or `.meas`ures its answer. A bench
whose answer is post-processing — a phase margin off a swept response, a crossover frequency, a
1 % settling time, a band edge from a device's region — has no printed scalar to read, so if that
maths lives in an `experiments/NNN-*/run.py`, `make certify` has nothing to freeze, `make check`
reproduces nothing, and the reference exists only inside a report. Put it HERE: the harness
(`metrics.run_decks`, hence `evaluate`/`certify`/`check`) and the experiment call the same
function, so the scorecard and the report agree by construction rather than by review.

Fill `PRODUCES` and `reduce()`. A bare template produces nothing and every caller no-ops, so a
design whose decks really do print their answers can ignore this file and map the printed measures
in `metrics.KEYMAP` instead. Most designs need both: the printed operating-point scalars stay in
the record beside the reduced columns.

Keep this module import-light (no simulator, no PDK): it is imported by `metrics`, by the
experiments, and by the tests, on machines where nothing can simulate.
"""

from __future__ import annotations

# Which bench answers which scorecard column. `metrics.KEYMAP` is built from this, so a key
# produced here reaches the scorecard un-namespaced; anything not listed stays `<bench>.<key>` —
# visible in the record, never a column. Name the spec ids in a comment, so the trail from a
# bound in `harness.yaml` to the code that answers it is readable here.
PRODUCES: dict[str, tuple[str, ...]] = {
    # "ac":  ("gain_db", "ugf_mhz"),   # S1, report-only
    # "stb": ("pm_deg",),              # S2
}


def reduce(bench: str, run) -> dict:
    """The scorecard contribution of one bench, from its raw result. Unknown bench -> `{}`.

    `run` is `design.sim.Run` — `run.measures` (printed/`.meas` scalars), `sim.dataset(run)` for a
    waveview dataset (the platform's measurement registry: `spicexplorer_waveview.measure`),
    `sim.raw(run)` for the rawfile. Return the keys this bench declares in `PRODUCES`, already
    unit-scaled to the spec's keys (`ts_ns`, `power_uw`), because the spec's bounds are.

    Deterministic and side-effect free: it is called inside a parallel batch, and its output is
    what `--certify` freezes.
    """
    return {}


def keymap() -> dict[tuple[str, str], tuple[str, float]]:
    """`metrics.KEYMAP` rows for `PRODUCES`: each produced key promoted under its own name."""
    return {(b, k): (k, 1.0) for b, keys in PRODUCES.items() for k in keys}
