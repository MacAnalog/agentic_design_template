# Environment

KIND: REFERENCE (procedural gotchas; recipes that outgrow this file go to `doc/memory/procedural/`)

| item | value |
|---|---|
| PDK | <name>, pinned at <git SHA / version>; its ngspice init file is `$SPICE_USERINIT_DIR/.spiceinit` (**required**: the lane refuses to run without it) |
| simulator lane | native ngspice through `lab/sim.py` = this repo's policy over the platform's `spicexplorer_core.spice_engine.run_deck`: the binary is `$<sim_env>` (`harness.yaml`; default by the prefix rule from `exp_env`, e.g. `FOO_EXP` → `FOO_NGSPICE`, `SIM_NGSPICE` when `exp_env` has no prefix), else `ngspice` on PATH |
| corner sections | <names as the PDK spells them> |
| work dir | `$<work_env>` (`harness.yaml`; prefix rule → `FOO_WORK` / `SIM_WORK`), else `$SX_SCRATCH/<design>-<checkout hash>/runs/<label>-<deck hash>/` (else `~/sx-scratch/…`); per checkout, never inside the repo, never under `/tmp` (rejected), never a tool name in the path |
| per-run init | every run dir gets `.spiceinit` = the PDK's file + `lab.sim.SPICEINIT_EXTRA` lines (a compatibility `set`, an extra `osdi` load); a cwd `.spiceinit` shadows `$SPICE_USERINIT_DIR` and `~/.spiceinit`, which is why it is copied, not referenced |
| doctor | `make doctor` simulates a one-resistor deck and requires `i_ma = 1` parsed from the log, a rawfile and the per-run init marker; it fails when `SPICE_USERINIT_DIR` is unset or its `.spiceinit` is empty. Once the design has a PDK device, call `preflight(deck, expect)` with its own probe |

## Gotchas

- ngspice exits 0 after a failed operating point and leaves a rawfile full of zeros. `run_deck`
  scans the log before anything is trusted (`spicexplorer_core.spice_engine.sim_log.fatal_lines`;
  `lab.sim.SimError` is the platform's `DeckRunError`) and raises on every error-level line:
  `Error:` lines (e.g. `Error: RHS "v(nowhere)*2" invalid`), the bare strings
  `doAnalyses: iteration limit reached`, `Transient solution failed`, `timestep too small`,
  `singular matrix`, `Unknown model type`, `could not find a valid modelname`, `Error on line`,
  `simulation interrupted`, and the one `Warning:` that hides a wrong deck —
  `'r1 a 0' is not a valid resistor instance line, ignored!` (a dropped device gives `i_ma = -0.0`
  and a rawfile). `Warning:`-prefixed forms (`Warning: singular matrix` during gmin stepping) are
  recoverable and do not fail the run. A non-zero exit code always fails it (`Run.rc`); so does a run
  with neither a rawfile nor a scalar (this repo's rule, in `lab.sim.run`).
- A failed `.meas` is not fatal. ngspice-45 prints `Error: measure  bad  when(WHEN) : out of interval`
  followed by ` meas tran bad when v(a)=5 failed!`; the lane skips that `Error:` line and returns
  the name in `Run.failed`, which `lab.metrics.measure` turns into NaN. Successful measures print
  `good                =  1.500000e-09` and land in `Run.measures` (`sim.parse_measures` =
  `spicexplorer_core.spice_engine.sim_log.parse_measures`, re-exported by `spicexplorer_waveview`;
  it reads stdout and stderr, since a body `.meas` in batch mode reports on stderr). A `print`
  scalar is read only for a named vector — `let x = …` then `print x` — never `print <expression>`.
- Two runs of the same label and deck at once: the second raises `SimError(... is busy)` instead of
  clobbering the first (`.busy` holds `<pid> <host>`: a dead or unparsable owner is reclaimed, another
  user's live process or a fresh foreign-host marker stays busy); different decks under one label get different directories (deck hash).
- The PDK init file spells paths as `$PDK_ROOT/$PDK`; the lane defaults both from
  `SPICE_USERINIT_DIR` when they are unset.
- <the first trap this lane set for you, and the fix>
