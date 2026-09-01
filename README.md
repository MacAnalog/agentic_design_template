# agentic-design-template

A starting point for an agent-first analog design repo. The reusable machinery (run ledger,
lints, context pack, spec checks) comes from the SpiceXplorer platform package
`spicexplorer-harness`; this repo holds only what is specific to one design: `harness.yaml`,
the docs under `doc/`, and the `lab/` code that builds decks and measures them.

## Instantiate

1. Copy the tree, fill `harness.yaml` and every `<…>` in `CLAUDE.md` and `doc/`.
2. Implement `lab/dut.py` (`Design.deck`) and `lab/metrics.py` (`measure`).
3. Certify a reference, `make freeze`, add it to `frozen:` in `harness.yaml`.
4. `make lint` must pass before the first experiment.

Requires the platform checkout beside this repo (`PLATFORM=../../spicexplorer-platform`,
override on the `make` line).
