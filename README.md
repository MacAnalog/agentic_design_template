# agentic-design-template

A starting point for an agent-first analog design repo. The reusable machinery (run ledger,
lints, context pack, spec checks) comes from the SpiceXplorer platform package
`spicexplorer-harness`; this repo holds only what is specific to one design: `harness.yaml`,
the docs under `doc/`, the `design/` code that builds decks and measures them, and the agent
definitions and method notes under `.claude/`.

## Instantiate

1. Copy the tree; fill `harness.yaml`, `pyproject.toml` (name, description) and every `<…>`
   in `CLAUDE.md` and `doc/`. Rename the design package: `git mv design <name>`, set `PACKAGE`
   in `scripts/lint.py`, and update the imports (`make lint` checks the package is importable).
   It is named for the DESIGN — the instances are `ldo/` and `mzm_tx/`.
2. `uv sync` — the harness, core and waveview are editable path dependencies on the sibling
   platform checkout (`../../spicexplorer-platform`); edit those paths in `pyproject.toml` if the
   repo lives elsewhere (every further `spicexplorer-*` member a design pulls in must be named
   in both `dependencies` and `[tool.uv.sources]`).
3. `make doctor` must report the lane alive (`design/sim.py` is a thin policy layer over the
   platform's `run_deck`: a one-resistor deck through ngspice with a per-run `.spiceinit`). Then
   implement `design/dut.py` (`benches()` + `deck(bench)`) and `design/metrics.py`'s `KEYMAP`;
   `make test` covers the generic modules and the scorecard lifecycle.
4. `make certify` (add `ARGS="--author X --verified-by Y"` once a second actor has re-measured it),
   `make freeze`, add the dir to `frozen:` and the scorecard to `reference_scorecard:`.
5. `make lint` must pass before the first experiment. For the layout lane, uncomment the
   `spicexplorer-gmid` / `-layout` / `-signoff` sources in `pyproject.toml` and `uv sync`.

## Layout

| path | what |
|---|---|
| `harness.yaml` | the design described to the harness: spec rows, frozen dirs, denylist, ledger columns |
| `CLAUDE.md` | the entry map agents read first |
| `doc/` | target spec, design reference (constraints), benches, environment, experiment log, journal + index, `reviews/` (verifier reports), the memory model |
| `design/` | generic, imported as-is — thin wrappers over the platform: `sim` (this repo's where/which/what policy over `spicexplorer_core.spice_engine.run_deck`), `stimulus` and `eye` (re-exports of `spicexplorer_waveview.stimulus`/`.eye`: PRBS/PAM4/PWL, symbol-aware eye metrics + BT4 receiver), `exp` (labelled batches, markdown), `plot` (spec boxes); per design: `dut` (the sizing point → deck), `metrics` (measure, check, log). The `design/` → platform table is in `doc/journal/design-consolidated-from-three-lanes.md` |
| `tests/` | `make test`: the generic `design/` modules (the live-lane test skips without ngspice) |
| `scripts/lint.py` | repo-specific checks on top of the harness |
| `layout/` | the layout of record as code: `gen_cell.py` (generator contract, `LayoutParams`, the per-net obstacle map) and `signoff.py` (build → render → DRC → current density → LVS → PEX → the cell's own benches) |
| `experiments/NNN-*/` | one directory per hypothesis; `_template/` is the shape — `README.md`, `run.py` (simulates into git-ignored `out/` and committed `figs/`) and `mk_readme.py` (regenerates the README from `out/*.json`) |
| `notebooks/` | executed in place by `make notebooks`, outputs committed |
| `pdf/` | papers + `INDEX.md` (cite by handle) |
| `.claude/agents/` | variant-runner, signoff-verifier, schematic-builder, paper-analyst, gardener |
| `.claude/skills/` | the visual-evidence methods: schematic of record, testbench schematics, findings as plots, layout evidence |
| `runs/` | `ledger.ndjson`, git-ignored; keeper numbers graduate into experiment READMEs |
