# CLAUDE.md — <design name> (agentic-design template)

**Map, not manual.** This file routes; the docs hold the substance. When instantiating the
template, replace every `<…>`, fill `harness.yaml`, rename the design package `design/` to this
design's name (`git mv design <name>`, update `PACKAGE` in `scripts/lint.py` and the imports —
instances use `ldo/`, `mzm_tx/`), and delete this sentence.

## Mission

<One paragraph: the block, the PDK and supply, the headline number to beat and the yardstick
it is measured against.> The spec of record is `doc/target-spec.md`; its machine twin is the
`spec:` block in `harness.yaml`, and `make lint` refuses to let the two drift.

## Read this before that

| you are about to… | read first |
|---|---|
| anything | `doc/target-spec.md` — the acceptance box, pass/fail definitions |
| measure something | `doc/benches.md` — reference-first: fast metrics iterate, frozen definitions certify |
| touch the DUT / model it | `doc/design-reference.md` — device map, validated model, the constraints every candidate must respect |
| pick a paper / technique | `pdf/INDEX.md` |
| run simulations | `design/` module docstrings + `doc/environment.md` (lanes, simulator gotchas) |
| start an experiment | copy `experiments/_template/`; add one row to `doc/experiment-log.md` |
| learn from / add a lesson | `doc/journal.md` (index); one file per entry in `doc/journal/`; supersede, never delete |
| know what to read/write when | `doc/memory/README.md` — the four memory tiers and the write-risk ordering |

## Harness commands

`spicexplorer-harness` (platform package, an editable path dependency — `uv sync` once per
checkout) does the generic work, driven by `harness.yaml`; `Makefile` wraps it.

- `make doctor` — is the simulation lane alive? `design/sim.py` (this repo's policy over the platform's
  `spicexplorer_core.spice_engine.run_deck`) simulates a one-resistor deck and passes only on a
  parsed scalar + rawfile + the per-run `.spiceinit` marker (`doc/environment.md`).
- `make test` — the generic `design/` modules (`sim`, `stimulus`, `eye`, `exp`, `plot`; `stimulus`/`eye`
  are re-exports of `spicexplorer_waveview`), pytest; the live-lane test skips without ngspice.
- `make pack K="noise irn"` — assemble **working memory** for a task. Run at task start;
  re-run with `S="fc drifted after cap swap"` on any new failure signature before diagnosing.
- `make lint` — repo invariants (`harness.yaml` drives them). Failure messages carry their fix.
- `make check` — lint + the reference reproduces its certified scorecard (SKIP, exit 0, until
  `reference_scorecard:` names one).
- `make runs ARGS="--fails | --best <metric> | --exp NNN | --kind thd | --where topology=b"` —
  query the run ledger (`runs/ledger.ndjson`; every `design.metrics.evaluate()` appends a row).
- `make freeze` — write `SHA256SUMS` into the frozen dirs after certifying a reference.

## Rules (mechanically enforced where possible; the rest is contract)

1. **Reference first.** A number that has not passed the frozen definitions is a claim.
2. **Decks are built, never text-edited.** A sizing point is a `design.dut.Design`; every deck is
   generated from it. Frozen dirs are sha-locked.
3. Every experiment: **falsifiable hypothesis first**; a control whenever a knob moves.
4. Findings are **tables or plots**; prose is interpretation. Keeper numbers graduate from the
   ledger into the experiment README — the repo is the memory.
5. **Parallelize batches** (`spicexplorer_harness.batch(items, fn, env=H.jobs_env)`, or
   `design.exp.run_batch(designs, score)`; the width env var is `jobs_env` in `harness.yaml`).
6. **Clean provenance.** Reference the PDK by name, pin its version in `doc/environment.md`,
   never vendor model bytes. `denylist:` in `harness.yaml` is a build failure, not a style note.
7. **Designer ≠ verifier.** Delivery claims are re-measured from raw artefacts.
8. **Gap-as-signal.** If you struggle, fix the harness (lint, helper, doc line) and journal it.
9. **Sim economy.** Expensive runs only after the cheap scorecard passes the box.
10. **Write-risk ordering.** Episodic writes are automatic; semantic writes need provenance and
    supersede-don't-delete; procedural writes (`design/`, `scripts/`, agent defs, this file) are
    human-reviewed — agents propose diffs, never self-apply them.

## Agents and methods

In `.claude/agents/` (each starts from `make pack`, reads `harness.yaml`, obeys rules 7–10):

- `paper-analyst` — one paper → a falsifiable technique brief + its `pdf/INDEX.md` row. Never simulates.
- `variant-runner` — parallel netlist-lane batches; scorecard tables only; reference first row, control when a knob moves.
- `signoff-verifier` — independent re-measurement of delivery claims from raw artefacts (rule 7). Reports; never fixes.
- `schematic-builder` — the reviewable `.sch`/`.sym` of record, proven equal to netlist and simulation.
- `gardener` — report-only consistency sweep. Has no write tools, by design.

Visual evidence is not optional: the methods in `.claude/skills/` — `schematic-of-record`,
`testbench-schematic` (components, not text), `findings-as-plots` (spec boxes drawn on every
figure), `layout-evidence` (generator → GDS → DRC/LVS/PEX → review overlay) — say how each
artefact is produced and gated. Layout work uses the workspace's `layout-*` agents.

## Parallel sessions & blast radius

One experiment = one session = one git worktree on `feat/NNN-<technique>`; `EXP=NNN` stamps the
ledger. **Put the worktree at the same directory depth as this repo** (e.g.
`git worktree add ../<repo>-<name>`, not `../wt/<name>`): the harness is a *relative* path
dependency (`../../spicexplorer-platform/...` in `pyproject.toml`), so a deeper worktree cannot
`uv sync` without a symlink hack. The ledger and work dirs are per checkout. Shared docs (`doc/journal.md`,
`doc/experiment-log.md`, `pdf/INDEX.md`) are written at close-out only; during the work, write
into your own `experiments/NNN-*/README.md`.

## Git

`feat/<name>` off `main`, PR, squash. **Ask before pushing.** Never commit `runs/`, work dirs,
rawfiles or PDK content.
