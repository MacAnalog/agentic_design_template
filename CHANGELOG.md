# Template releases

KIND: REFERENCE (what each template version changed, and whether a design already under way can
take it)

A design is **copied** from this template, never submoduled to it, so it records the version it was
cut from in `.sx/template-version` and pulls later work with `make template-update`. Versions are
`MAJOR.MINOR`, written `#.##`:

- **MINOR** (`1.00` → `1.01`) — generic work: a module every design gets, a lint check, a hook in
  the lane, docs. It propagates into a design already under way, through a three-way merge that
  leaves anything the design edited to a human.
- **MAJOR** (`1.x` → `2.0`) — the scaffold's shape changed: a renamed module, a different
  `harness.yaml` contract, a lifecycle command that moved. `make template-update` refuses to cross
  one and prints the entry below instead; each MAJOR entry carries its migration steps.

Check where you stand with `make template-status`. Releases are git tags, `v<version>`.

## v1.04 — apply file by file, and say what each file did

MINOR. `git apply` is atomic: on the first real propagation, one file the design had never carried
(a test module it dropped) aborted the whole patch and silently rolled back every file that had
already merged. Each file is now applied on its own, and the run prints one line per file — `added`,
`merged`, `skipped` (the design does not carry the file the change edits) or `CONFLICT`. A design
therefore receives everything that can land, and the report names exactly what did not.

## v1.03 — the package's generic modules propagate too

MINOR. `1.02` held back `metrics.py` and `bench.py` with `dut.py`, which meant a design could never
receive the scorecard-lifecycle and reduction work those files carry — the very thing `1.01` added.
Only `dut.py` is now design-owned inside the package: the template's is a stub, so propagating its
changes into a real topology is conflict noise and nothing else. Everything else merges three-way,
and a conflict inside `metrics.py` (typically at `KEYMAP`) is a decision for the designer, not a
failure of the update.

## v1.02 — template versioning

MINOR. A design can now tell which template it came from and take later minor work.

- `.sx/template-version` (`#.##`), inherited by every repo created from this template.
- `make template-status` / `make template-update` (`scripts/template_update.py`): fetch the
  template as a remote, diff the recorded release against the target, apply with a three-way merge,
  and stop with conflict markers wherever the design's own edits meet the template's. Nothing is
  committed and nothing is overwritten silently.
- The design owns `harness.yaml`, its `doc/`, `pyproject.toml`, `experiments/`, `decks/`, `layout/`
  and, inside its package, `dut.py`, `bench.py` and `metrics.py`; everything else propagates.
- The instantiation rename is handled: the package half of the diff is re-rooted from `design/`
  onto whatever `harness.yaml` names. Hunks whose *text* mentions the template's `design.` package
  still arrive spelled that way — run `make lint && make test` after an update and fix what they
  report.

## v1.01 — certifiable reductions, portable decks

MINOR. Both halves come from certifying a real design (issue #13).

- `design/bench.py`: the package-level reduction (`PRODUCES` + `reduce()`) that the harness and the
  experiments share. A bench whose answer is post-processing (phase margin, crossover, settling
  time) is certifiable only because the reduction lives here rather than in an experiment's
  `run.py`; `metrics.KEYMAP` is built from `PRODUCES` and `metrics.run_decks` merges the reduction
  into each bench record before anything is promoted, logged or frozen.
- `design/sim.py`: `DECK_VARS` + `resolve()` — a machine-specific path is named in the deck as
  `$VAR` and substituted inside `run()`, so what is built, logged, frozen and diffed stays portable.
  `make doctor` fails when a declared variable is unset.
- `scripts/lint.py`: `deck_portable` refuses an absolute include path in a frozen deck.
- CLAUDE.md rules 1 and 2, `doc/benches.md` and `doc/environment.md` state both rules.

## v1.00 — first tagged release

The template as it stood on 2026-09-09: the harness lifecycle (`certify` / `freeze` / `baseline` /
`check`), the ngspice lane wrapper, the ledger and context pack, the `deck_rebuild` and
`spec_quotes` lints, the linked agents and skills, the layout and sign-off stubs, and the docs
skeleton. Designs cut before this tag can record `1.00` and update from there; the first update may
raise conflicts a human resolves, never a silent overwrite.
