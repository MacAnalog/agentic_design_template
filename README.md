# agentic-design-template

A starting point for an agent-first analog design repo. The parts every design shares — run
ledger, lints, context pack, spec checks — come from the SpiceXplorer platform package
`spicexplorer-harness`. This repo holds only what is specific to one design: `harness.yaml`,
the docs under `doc/`, the `design/` code that builds decks and measures them, and the agent
definitions and method notes under `.claude/`.

## Instantiate

1. `export SX_ROOT=<your spicexplorer-workspace checkout>` (the lab's `~/.sx_env` does this), then
   get the tree. Prefer `make new` in `macanalog-design-directory`: it names the repo by the lab
   convention, creates it from the template on GitHub, clones it and runs the `make init` of step 2
   for you. Otherwise copy the tree by hand.
2. `make init`: it links `.sx/platform -> $SX_ROOT/spicexplorer-platform`, initialises the
   `.sx/skills` library (analog-skill-directory) with its agent/skill links, and runs `uv sync`.
   Repeat in every new checkout or worktree.
3. Fill `harness.yaml`, `pyproject.toml` (name, description) and every `<…>` in `CLAUDE.md`
   and `doc/`.
4. Rename the design package: `git mv design <name>`, set `package:` in `harness.yaml`, and
   update the imports plus `Makefile` and `experiments/_template/`. The package is named for the
   DESIGN — the instances are `ldo/` and `mzm_tx/`. `make lint` checks the package is importable;
   `layout/signoff.py` and `scripts/lint.py` resolve it from `package:` and need no edit.
5. The harness, core and waveview are editable path dependencies through `.sx/platform`
   (`make init` made the link; a read-only `SX_ROOT` is fine). A design that pulls in a further
   `spicexplorer-*` member names it in both `dependencies` and `[tool.uv.sources]`, then runs
   `uv sync` once.
6. `make doctor` must report the lane alive: it runs a one-resistor deck with a per-run
   `.spiceinit` through ngspice, driven by `design/sim.py` — this repo's policy layer over the
   platform's `run_deck`. Then implement `design/dut.py` (`benches()` + `deck(bench)`) and
   `design/metrics.py`'s `KEYMAP`. `make test` covers the generic modules and the scorecard
   lifecycle.
7. `make certify` (add `ARGS="--author X --verified-by Y"` once a second actor has re-measured it),
   add the dir to `frozen:` and the scorecard to `reference_scorecard:`, then `make freeze`.
8. `make lint` must pass before the first experiment.
9. For the layout lane, uncomment the `spicexplorer-gmid` / `-layout` / `-signoff` sources in
   `pyproject.toml` and `uv sync`.

## Layout

| path | what |
|---|---|
| `harness.yaml` | the design described to the harness: spec rows, frozen dirs, denylist, ledger columns |
| `CLAUDE.md` | the entry map agents read first |
| `doc/` | target spec, design reference (constraints), benches, environment, experiment log, journal + index, `reviews/` (verifier reports), the memory model |
| `design/` | generic wrappers over the platform, imported as-is: `sim` (this repo's where/which/what policy over `spicexplorer_core.spice_engine.run_deck`), `stimulus` and `eye` (re-exports of `spicexplorer_waveview.stimulus`/`.eye`: PRBS/PAM4/PWL, symbol-aware eye metrics + BT4 receiver), `exp` (labelled batches, markdown), `plot` (spec boxes). Written per design: `dut` (the sizing point → deck), `metrics` (measure, check, log). The `design/` → platform table is in `doc/journal/design-consolidated-from-three-lanes.md` |
| `tests/` | `make test`: the generic `design/` modules (the live-lane test skips without ngspice) |
| `scripts/lint.py` | repo-specific checks on top of the harness |
| `layout/` | the layout of record as code: `gen_cell.py` (generator contract, `LayoutParams`, the per-net obstacle map) and `signoff.py` (build → render → DRC → current density → LVS → PEX → the cell's own benches) |
| `experiments/NNN-*/` | one directory per hypothesis; `_template/` is the shape — `README.md`, `run.py` (simulates into git-ignored `out/` and committed `figs/`) and `mk_readme.py` (regenerates the README from `out/*.json`) |
| `notebooks/` | executed in place by `make notebooks`, outputs committed |
| `pdf/` | papers + `INDEX.md` (cite by handle) |
| `.sx/` | the per-checkout plumbing `make init` sets up: `platform` (git-ignored link to `$SX_ROOT/spicexplorer-platform`) and `skills` (the `analog-skill-directory` submodule: shared agents, skills, guard hooks, `bin/sx-link`) |
| `.claude/agents/` | links into `.sx/skills/agents/`: variant-runner, signoff-verifier, schematic-builder, paper-analyst, gardener + the layout chain (brief-author, designer, reviewer, schematic-codesign); design-specific agents are plain files beside them |
| `.claude/skills/` | links into `.sx/skills/skills/`: the visual-evidence methods (schematic of record, testbench schematics, findings as plots, layout evidence), gm/ID sizing + LUTs, current mirrors, layout annotation, neutral naming, the remote-simulator learning journal and the bridge's two simulator skills |
| `.claude/settings.json` | the one hook (`.sx/skills/hooks/cmc_ask_hook.py`): anything under `/CMC` asks for permission; nothing else is blocked (owner ruling 2026-09-07) |
| `runs/` | `ledger.ndjson`, git-ignored; the numbers worth keeping move into experiment READMEs |
