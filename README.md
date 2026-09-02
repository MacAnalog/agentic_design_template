# agentic-design-template

A starting point for an agent-first analog design repo. The reusable machinery (run ledger,
lints, context pack, spec checks) comes from the SpiceXplorer platform package
`spicexplorer-harness`; this repo holds only what is specific to one design: `harness.yaml`,
the docs under `doc/`, the `lab/` code that builds decks and measures them, and the agent
definitions and method notes under `.claude/`.

## Instantiate

1. Copy the tree; fill `harness.yaml`, `pyproject.toml` (name, description) and every `<…>`
   in `CLAUDE.md` and `doc/`.
2. `uv sync` — the harness is an editable path dependency on the sibling platform checkout
   (`../../spicexplorer-platform`); edit that path in `pyproject.toml` if the repo lives elsewhere.
3. Implement `lab/sim.py` (`preflight`, `run`), `lab/dut.py` (`Design.deck`) and
   `lab/metrics.py` (`measure`). `make doctor` must report the lane alive.
4. Certify a reference, `make freeze`, add it to `frozen:` in `harness.yaml`.
5. `make lint` must pass before the first experiment.

## Layout

| path | what |
|---|---|
| `harness.yaml` | the design described to the harness: spec rows, frozen dirs, denylist, ledger columns |
| `CLAUDE.md` | the entry map agents read first |
| `doc/` | target spec, design reference (constraints), benches, environment, experiment log, journal + index, the memory model |
| `lab/` | `sim` (lane), `dut` (the sizing point → deck), `metrics` (measure, check, log) |
| `scripts/lint.py` | repo-specific checks on top of the harness |
| `experiments/NNN-*/` | one directory per hypothesis; `_template/README.md` is the shape |
| `pdf/` | papers + `INDEX.md` (cite by handle) |
| `.claude/agents/` | variant-runner, signoff-verifier, schematic-builder, paper-analyst, gardener |
| `.claude/skills/` | the visual-evidence methods: schematic of record, testbench schematics, findings as plots, layout evidence |
| `runs/` | `ledger.ndjson`, git-ignored; keeper numbers graduate into experiment READMEs |
