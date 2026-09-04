# Environment

KIND: REFERENCE (procedural gotchas; recipes that outgrow this file go to `doc/memory/procedural/`)

| item | value |
|---|---|
| PDK | <name>, pinned at <git SHA / version>; its ngspice init file is `$SPICE_USERINIT_DIR/.spiceinit` |
| simulator lane | native ngspice through `lab/sim.py`: `$<PREFIX>_NGSPICE` (PREFIX from `exp_env`, e.g. `LDO_EXP` → `LDO_NGSPICE`; `SIM_NGSPICE` when `exp_env` has no prefix), else `ngspice` on PATH, else `~/local/bin/ngspice` |
| corner sections | <names as the PDK spells them> |
| work dir | `$<PREFIX>_WORK`, else `$SX_SCRATCH/<design>-<checkout hash>/runs/<label>/` (else `~/sx-scratch/…`); per checkout, outside the repo, never a tool name in the path |
| per-run init | every run dir gets `.spiceinit` = the PDK's file + `spiceinit_extra` lines (e.g. `set ngbehavior=hsa` for the IHP HBTs); a cwd `.spiceinit` shadows `$SPICE_USERINIT_DIR` and `~/.spiceinit`, which is why it is copied, not referenced |
| doctor | `make doctor` simulates a one-resistor deck and requires `i_ma = 1` parsed from the log, a rawfile and the per-run init marker; once the design has a PDK device, call `preflight(deck, expect)` with its own probe |

## Gotchas

- ngspice exits 0 after a failed operating point and leaves a rawfile full of zeros: `lab.sim.run`
  scans the log (`Error:` lines, `doAnalyses: iteration limit reached`, `Transient solution
  failed`, `timestep too small`, `singular matrix`, unknown model) and raises `SimError` before
  anything is trusted.
- `print`/`meas` scalars are read from the log (`sim.parse_measures`); a `meas` that fails comes
  back by name in `Run.failed` and lands as NaN in the scorecard.
- The PDK init file spells paths as `$PDK_ROOT/$PDK`; the lane defaults both from
  `SPICE_USERINIT_DIR` when they are unset.
- <the first trap this lane set for you, and the fix>
