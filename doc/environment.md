# Environment

KIND: REFERENCE (procedural gotchas; recipes that outgrow this file go to `doc/memory/procedural/`)

| item | value |
|---|---|
| `SX_ROOT` | the SpiceXplorer workspace checkout (`spicexplorer-workspace`: platform + tools + docs). On the lab workstation it is the admin-updated read-only copy at `/opt/macanalog/spicexplorer-workspace`; anywhere else it is your own clone. `~/.sx_env` exports it. `make init` turns it into the git-ignored link `.sx/platform`, and `pyproject.toml` installs the `spicexplorer-*` packages through that link because uv does not expand env vars in a source path. The platform's own root variable, `SPICEXPLORER_ROOT`, is `$SX_ROOT/spicexplorer-platform` |
| `.sx/skills` | the `analog-skill-directory` submodule (shared agents, skills, guard hooks), pinned per design. `make init` runs `bin/sx-link`, which points `.claude/agents/*` and `.claude/skills/*` at it, one symlink per entry; `make lint` checks that every one resolves |
| PDK | <name>, pinned at <git SHA / version>; its ngspice init file is `$SPICE_USERINIT_DIR/.spiceinit` (**required**: the lane refuses to run without it) |
| simulator lane | native ngspice through `design/sim.py`, this repo's policy over the platform's `spicexplorer_core.spice_engine.run_deck`. The binary is `$<sim_env>` from `harness.yaml`, defaulted by the `<PREFIX>` rule (`FOO_EXP` → `FOO_NGSPICE`; `SIM_NGSPICE` when `exp_env` has no prefix), else `ngspice` on PATH |
| `<PREFIX>` | the harness env-name prefix, derived from `exp_env`: `FOO_EXP` → `FOO_`, and `SIM_` when `exp_env` carries no prefix. The platform applies the same rule to `sim_env` and `work_env`. It is NOT derived from `sim_env`, which an instance may set to an unrelated binary name |
| corner sections | <names as the PDK spells them> |
| deck variables | `design.sim.DECK_VARS` declares the machine-specific paths a deck names as `$VAR`, such as a model library installed only on some machines; `sim.run` resolves them at the moment of simulating. The deck text, the ledger row and the frozen reference stay portable, and `deck-portable` in `scripts/lint.py` refuses an absolute include in a frozen deck. Pin WHICH library by revision name in the PDK row above, never by its path — and name that revision in `design.sim.DECK_VAR_PINS`, which makes `resolve()` refuse a variable pointing at another one (`<NAME>_ALLOW_MISMATCH=1` for a deliberate one-off). Set `design.sim.DECK_VAR_SCOPE` to a short tag for this design and export `<SCOPE>_<NAME>`: the bare name is the text inside every frozen deck, so it is shared, and one export of it can feed two repos |
| work dir | `$<work_env>` from `harness.yaml` (`<PREFIX>` rule → `FOO_WORK` / `SIM_WORK`), else `$SX_SCRATCH/<design>-<checkout hash>/runs/<label>-<deck hash>/`, else `~/sx-scratch/…`. One work dir per checkout. It is never inside the repo, never under `/tmp` (rejected), and never carries a tool name in its path |
| per-run init | every run dir gets a `.spiceinit` = the PDK's file + `design.sim.SPICEINIT_EXTRA` lines (a compatibility `set`, an extra `osdi` load). A `.spiceinit` in the cwd shadows both `$SPICE_USERINIT_DIR` and `~/.spiceinit`, so the lane copies the PDK's file into each run dir rather than referencing it |
| layout lane | **two interpreters, deliberately**. `$<PREFIX>_GDS_PYTHON` runs the generator, which needs gdsfactory + the PDK cells; it has no default, and an unset variable raises an error carrying its fix instead of falling back to a home path. DRC/LVS/PEX run from this venv through `spicexplorer_signoff`. `SIGNOFF_PYTHON`, if set, must import BOTH the PDK runset's own dependencies and the layout API; an interpreter missing one reports `matched=False` with an EMPTY reason and puts the traceback only in the log |
| sign-off PDK | `layout/signoff.py` passes one `PDK` to every stage: the rule deck, the render colours and the electromigration limits. Set the module constant or `$<PREFIX>_PDK`. There is deliberately **no default**, because each platform runner has its own, and a PDK that is valid but not this design's passes every stage and means nothing |
| physical lanes | `spicexplorer-gmid` / `-layout` / `-signoff` are commented out of `pyproject.toml`, so the default venv covers simulation only and installs none of the three. Uncomment them + one `uv sync` before the sizing (gm/ID), layout or PEX work starts |
| doctor | `make doctor` simulates a one-resistor deck and requires `i_ma = 1` parsed from the log, a rawfile and the per-run init marker; it fails when `SPICE_USERINIT_DIR` is unset or its `.spiceinit` is empty. Once the design has a PDK device, call `preflight(deck, expect)` with its own probe |

## Gotchas

- ngspice exits 0 after a failed operating point and leaves a rawfile full of zeros. `run_deck`
  therefore reads the log before it trusts any result
  (`spicexplorer_core.spice_engine.sim_log.fatal_lines`; `design.sim.SimError` is the platform's
  `DeckRunError`) and raises on every error-level line: `Error:` lines (e.g.
  `Error: RHS "v(nowhere)*2" invalid`), the bare strings
  `doAnalyses: iteration limit reached`, `Transient solution failed`, `timestep too small`,
  `singular matrix`, `Unknown model type`, `could not find a valid modelname`, `Error on line`,
  `simulation interrupted`, and the one `Warning:` that hides a wrong deck —
  `'r1 a 0' is not a valid resistor instance line, ignored!` (a dropped device gives `i_ma = -0.0`
  and a rawfile). `Warning:`-prefixed forms (`Warning: singular matrix` during gmin stepping) are
  recoverable and do not fail the run. A non-zero exit code always fails a run (`Run.rc`), and so
  does a run with neither a rawfile nor a scalar (this repo's rule, in `design.sim.run`).
- A failed `.meas` is not fatal. ngspice-45 prints `Error: measure  bad  when(WHEN) : out of interval`
  followed by ` meas tran bad when v(a)=5 failed!`. The lane skips that `Error:` line and returns
  the measure's name in `Run.failed`, and `design.metrics.measure` turns it into NaN. A successful
  measure prints `good                =  1.500000e-09` and lands in `Run.measures`
  (`sim.parse_measures` = `spicexplorer_core.spice_engine.sim_log.parse_measures`, re-exported by
  `spicexplorer_waveview`; it reads stdout and stderr, since a body `.meas` in batch mode reports
  on stderr). A `print` scalar is read only for a named vector — `let x = …` then `print x` —
  never `print <expression>`.
- Start two runs of the same label and deck at once and the second raises `SimError(... is busy)`
  rather than overwriting the first. `.busy` holds `<pid> <host>`: a dead or unparsable owner is
  reclaimed, while another user's live process or a fresh foreign-host marker stays busy. Different
  decks under one label get different directories (deck hash).
- The PDK init file spells paths as `$PDK_ROOT/$PDK`; the lane defaults both from
  `SPICE_USERINIT_DIR` when they are unset.
- **Pin the PDK by commit, not by name.** Record the exact revision (and the model-card revision
  if the PDK versions them separately) in the table above: a PASS measured against a different
  PDK revision than the baseline's is not comparable, and nothing else in the repo records it.
- **Trust `--version`, not the install path.** A tool unpacked under a directory named for one
  release is routinely a different one.
- <the first trap this lane set for you, and the fix>
