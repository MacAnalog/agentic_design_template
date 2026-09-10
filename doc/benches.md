# Benches

KIND: REFERENCE (what certifies what)

**Reference-first policy.** Fast metrics (`design.metrics.evaluate`) iterate; the frozen
definitions certify. A number that has not passed through them is a claim.

A bench answers in one of two ways and both end in the same scorecard column:

- **it prints its answer** (`print` / `.meas`) — `design.metrics.KEYMAP` maps `(bench, printed
  measure)` onto the unit-scaled spec key;
- **its answer is post-processing** (a phase margin off a swept response, a crossover frequency, a
  settling time, a band edge from a device's region) — the maths lives in `design/bench.py`
  (`PRODUCES` + `reduce()`), and `KEYMAP` is built from `PRODUCES`.

**That is the only place a name and a scale factor live** — a reader must be able to follow one
number from the deck's `print` line, or from the reduction that reads its waves, to the box, and
the table below is where that trail is written down. The reduction sits in the package rather than
in an experiment for one reason: `make certify` freezes what `metrics.run_decks` produced, so a
number computed inside an `experiments/NNN-*/run.py` cannot be certified and `make check` has
nothing to reproduce. The experiment calls the same `bench.reduce`, so its report and the certified
scorecard agree by construction.

| bench | what it measures | fast (iterate) | frozen (certify) | measure → key (scale) |
|---|---|---|---|---|
| <ac> | <the quantity> | <sweep, density> | <the definition of record> | `<gain>` → `gain_db`; `<pm>` → `pm_deg` |
| <op> | <the quantity> | | | `<i_supply>` → `power_uw` (×1e6) |
| <stb> | <the quantity> | | | `bench.reduce` → `pm_deg`, `ugf_mhz` (post-processed, not printed) |

**What sign-off adds that the fast scorecard does not run** — say it here, or a reader will
assume the box was checked everywhere it binds: <the off-nominal load / frequency / corner points,
the long-window definitions, the PVT set>. A spec that binds at corners pre-layout and is
re-measured only at nominal afterwards is a hole, not a footnote.

**When the reference is not at the target's operating point** — a certified reference bound to
its own supply, device family or load is a yardstick for SOME rows only. Split the spec table:
the rows the reference legitimately sets, and the rows set from the literature until a re-based
reference exists. Say which is which in `doc/target-spec.md`, per row.
