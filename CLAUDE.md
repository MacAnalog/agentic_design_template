# CLAUDE.md — <design name> (agentic-design template)

**Map, not manual.** This file routes; the docs hold the substance. When instantiating the
template, replace every `<…>`, fill `harness.yaml`, and delete this sentence.

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
| run simulations | `lab/` module docstrings + `doc/environment.md` (lanes, simulator gotchas) |
| start an experiment | copy `experiments/_template/`; add one row to `doc/experiment-log.md` |
| learn from / add a lesson | `doc/journal.md` (index); one file per entry in `doc/journal/`; supersede, never delete |
| know what to read/write when | `doc/memory/README.md` — the four memory tiers and the write-risk ordering |

## Harness commands

`spicexplorer-harness` (platform package) does the generic work; `Makefile` wraps it.

- `make pack K="noise irn"` — assemble **working memory** for a task. Run at task start;
  re-run with `S="fc drifted after cap swap"` on any new failure signature before diagnosing.
- `make lint` — repo invariants (`harness.yaml` drives them). Failure messages carry their fix.
- `make check` — lint + the reference reproduces its certified scorecard.
- `make runs ARGS="--fails"` — query the run ledger (`runs/ledger.ndjson`; every
  `lab.metrics.evaluate()` appends a row automatically).
- `make freeze` — write `SHA256SUMS` into the frozen dirs after certifying a reference.

## Rules (mechanically enforced where possible; the rest is contract)

1. **Reference first.** A number that has not passed the frozen definitions is a claim.
2. **Decks are built, never text-edited.** A sizing point is a `lab.dut.Design`; every deck is
   generated from it. Frozen dirs are sha-locked.
3. Every experiment: **falsifiable hypothesis first**; a control whenever a knob moves.
4. Findings are **tables or plots**; prose is interpretation. Keeper numbers graduate from the
   ledger into the experiment README — the repo is the memory.
5. **Parallelize batches** (`spicexplorer_harness.batch`, `JOBS`).
6. **Clean provenance.** Reference the PDK by name, pin its version in `doc/environment.md`,
   never vendor model bytes. `denylist:` in `harness.yaml` is a build failure, not a style note.
7. **Designer ≠ verifier.** Delivery claims are re-measured from raw artefacts.
8. **Gap-as-signal.** If you struggle, fix the harness (lint, helper, doc line) and journal it.
9. **Sim economy.** Expensive runs only after the cheap scorecard passes the box.
10. **Write-risk ordering.** Episodic writes are automatic; semantic writes need provenance and
    supersede-don't-delete; procedural writes (`lab/`, `scripts/`, agent defs, this file) are
    human-reviewed — agents propose diffs, never self-apply them.

## Agents

Not yet defined for the template (workspace plan `plan_agentic_design_template.md` T7). They
will read `harness.yaml` first and follow rules 7–10.

## Parallel sessions & blast radius

One experiment = one session = one git worktree on `feat/NNN-<technique>`; `EXP=NNN` stamps the
ledger. The ledger and work dirs are per checkout. Shared docs (`doc/journal.md`,
`doc/experiment-log.md`, `pdf/INDEX.md`) are written at close-out only; during the work, write
into your own `experiments/NNN-*/README.md`.

## Git

`feat/<name>` off `main`, PR, squash. **Ask before pushing.** Never commit `runs/`, work dirs,
rawfiles or PDK content.
