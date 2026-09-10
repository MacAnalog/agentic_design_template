# Template releases

KIND: REFERENCE (what each template version changed, and whether a design already under way can
take it)

A design is **copied** from this template, never submoduled to it, so it cannot pull. It records the
version it was cut from in `.sx/template-version` and takes later work with `make template-update`.
Versions are `MAJOR.MINOR`, written `#.##`:

- **MINOR** (`1.00` → `1.01`) — generic work: a module every design gets, a lint check, a hook in
  the lane, docs. It propagates into a design already under way. A file the design edited is merged
  three-way; where those edits meet the template's, the run leaves conflict markers for a human.
- **MAJOR** (`1.x` → `2.0`) — the scaffold's shape changed: a renamed module, a different
  `harness.yaml` contract, a lifecycle command that moved. `make template-update` refuses to cross
  one and prints the entry below instead; each MAJOR entry carries its migration steps.

`make template-status` prints the recorded version and the latest release. Releases are git
tags, `v<version>`.

## v2.00 — every artefact has a home (MAJOR: directories move)

**Why this is a MAJOR.** A three-way merge can change a file's contents; it cannot move a file.
2.00 renames one directory and adds another, so it crosses by script, not by merge:
`scripts/migrate_v1_to_v2.py` (`make template-migrate ARGS="--dry-run"` first). It moves things,
repoints `harness.yaml`, writes the new version, and commits nothing.

### What changed

| change | before | after |
|---|---|---|
| reference material is named for what it is, not its file format | `pdf/` | `references/` (`papers_dir`, `papers_index`) |
| the design of record has one tree, organized by simulation fidelity | `decks/reference/`, renders loose in `layout/` | `signoff/` — `schematic/`, `layout/`, and one directory per fidelity (`prelayout`, `postlayout-pex`, `postlayout-em`), each with `decks/`, `scorecard.json`, `figs/`, `tables/`, `REPORT.md` |
| an experiment says which phase of the design it belongs to | — | `**Phase:**` in its README, `Phase` first in `experiments_rows` |
| an experiment's numbers get a committed, diffable form | `figs/` only | `figs/` + `tables/`, written by the new `exp.csv` |
| the package stops carrying link-specific shims | `<pkg>/stimulus.py`, `<pkg>/eye.py` | import `spicexplorer_waveview.stimulus` / `.eye` directly. **Nothing is deleted from an existing design** |

### What it enforces

Two new checks in `scripts/lint.py`, both with their fix in the message:

- **`artifact-home`** — a committed `.png`, `.svg`, `.pdf`, `.csv` or `.gds` must sit in a home the
  repo has declared: `experiments/` (wide open — that is the working space), `signoff/`, `layout/`,
  `decks/`, `doc/`, `references/`, `notebooks/`. Raw simulator output is never committed at all; it stays in
  the scratch root. The reason is not tidiness: a reviewer who cannot find the evidence treats the
  claim as unsupported.
  **The escape hatch is a declaration, not an exemption.** A design with its own durable output
  directory — a physics lane, a report tree, an imported legacy set — adds one line to
  `ARTIFACT_HOMES` in its own `scripts/lint.py` saying what lives there. Measured across the
  owner's six designs, that is one or two lines each. The migration prints the count and the
  directories before you decide.
- **`signoff-index`** — every directory under `signoff/` appears in `signoff/README.md`, with what
  the number includes, its scorecard, its status and who signed it. An undescribed directory in the
  trusted tree looks certified and says nothing.

### Migration

**It applies only to a repo the harness describes.** Two of the lab's designs predate the template
and carry no `harness.yaml`; the script refuses them by name rather than moving their directories
and failing partway. A repo outside the harness contract stays outside it until it adopts the
template deliberately.

**Prerequisite: the design must already be at 1.04 or later** (`make template-update` first). 1.04
is where the file-by-file three-way apply this migration reuses was added; crossing from earlier
in one step would apply the whole patch atomically, and one missing file would silently roll back
every file that had merged. The script checks and refuses before it moves anything.

The script ships in 2.00, so a design still on 1.xx has to fetch it before it can run it. Two
lines, from the design's repo root:

```bash
git fetch --tags --force https://github.com/MacAnalog/agentic_design_template.git
git show v2.00:scripts/migrate_v1_to_v2.py > scripts/migrate_v1_to_v2.py && chmod +x scripts/migrate_v1_to_v2.py
```

Then, on a clean worktree (the script refuses a dirty one, so `git status` afterwards shows
exactly what it did):

```bash
python3 scripts/migrate_v1_to_v2.py --dry-run   # read the plan; nothing moves
python3 scripts/migrate_v1_to_v2.py             # apply it; nothing is committed
make lint && make test && make check            # the reference MOVED — prove it still reproduces
```

It does two things in order: takes 2.00's ordinary content changes by three-way merge, file by
file (the same machinery `make template-update` uses), then makes the moves a merge cannot make.
Conflicts are reported per file and are decisions, not failures — `scripts/lint.py` is the usual
one, where 2.00's two new checks meet the design's own.

Then fill each experiment's `**Phase:**` and the table in `signoff/README.md`, read `git status`,
and commit. The script refuses to run on a dirty worktree, so `git status` afterwards shows
exactly what it did.

**It never moves a frozen directory, and that is deliberate.** An earlier draft moved a single
unambiguous `decks/<ref>` into `signoff/prelayout/decks`. Trialled on a live design, that FAILS: a
certified `scorecard.json` names its own artefacts by path in its provenance block, so the move
invalidates the certification (`scorecard-recompute`: *"raw `decks/candidate/decks.sha256` is
missing"*). Regenerating it needs a live re-certification and a second actor's signature — a
deliberate act, never a side effect of a rename. The script now reports where the design of record
should end up and leaves the bytes alone; you point `signoff/` at it, and it moves for free the
next time you re-certify.

**Nor does it pick WHICH directory is the design of record** when several are frozen — and it
warns you not to let `reference_scorecard` pick either. That key means *the scorecard `make check`
reproduces*, which a design may legitimately point at a prior-art yardstick it is trying to beat.
Measured on a live design: the directory named `reference` was the yardstick and the one named
`candidate` was the design of record, so following the key would have promoted prior art into the
sign-off tree and left the real design behind.

## v1.05 — every document rewritten against the writing standard

MINOR, and it touches only prose. The lab's `design-writing` skill now says how any document in a
design repo is written, revised and audited: the field's own terminology and no coined labels, no
adjective without a number, what must be a table or a plot rather than a sentence, paragraphs a
designer can scan with the agent-grade detail layered underneath, and a contract per document type.

Every `.md` in this template was audited against it and rewritten, and each rewrite was checked by a
second pass for lost facts, false additions, broken structure and style regressions. Nothing that
any document asserts changed; the numbers, paths, commands, placeholders and tables are the same.
The word *reduction* is now defined where each document first uses it, which was the defect that
prompted the rule about coined nouns.

## v1.04 — apply file by file, and say what each file did

MINOR. `git apply` is atomic. On the first real propagation, one file the design had never carried —
a test module it dropped — aborted the whole patch and rolled back every file that had already
merged, without reporting it. `make template-update` now applies each file on its own and prints one
line per file: `added`, `merged`, `skipped` (the design does not carry the file the change edits) or
`CONFLICT`. A design receives every file that can land, and the report names the ones that did not.

## v1.03 — the package's generic modules propagate too

MINOR. `1.02` held back `metrics.py` and `bench.py` alongside `dut.py`, so a design could not
receive the scorecard-lifecycle and reduction work those files carry — the work `1.01` added.
Inside the package, only `dut.py` is design-owned now: the template's is a stub, so propagating its
changes into a real topology yields conflicts and nothing a design can use. Everything else merges
three-way. A conflict inside `metrics.py`, usually at `KEYMAP`, is a decision for the designer, not
a failure of the update.

## v1.02 — template versioning

MINOR. A design can now tell which template release it came from and take later minor work.

- `.sx/template-version` (`#.##`), inherited by every repo created from this template.
- `make template-status` / `make template-update` (`scripts/template_update.py`): fetch the
  template as a remote, diff the recorded release against the target, apply with a three-way merge,
  and stop with conflict markers wherever the design's own edits meet the template's. Nothing is
  committed and nothing is overwritten silently.
- The design owns `harness.yaml`, its `doc/`, `pyproject.toml`, `experiments/`, `decks/`, `layout/`
  and, inside its package, `dut.py`, `bench.py` and `metrics.py`; everything else propagates.
- `template_update.py` handles the instantiation rename: it re-roots the package half of the diff
  from `design/` onto whatever `harness.yaml` names. A hunk whose *text* names the template's
  `design.` package still arrives spelled that way, so run `make lint && make test` after an update
  and fix what they report.

## v1.01 — certifiable reductions, portable decks

MINOR. Both halves come from certifying a real design (issue #13).

- `design/bench.py`: the code that turns a bench's simulated waveform into the number the spec is
  written in — the bench's **reduction** (`PRODUCES` + `reduce()`) — shared by the harness and the
  experiments share. A bench whose answer is post-processing — phase margin, crossover, settling
  time — is certifiable only when the reduction lives here rather than in an experiment's `run.py`.
  `metrics.KEYMAP` is built from `PRODUCES`, and `metrics.run_decks` merges the reduction into each
  bench record before anything is promoted, logged or frozen.
- `design/sim.py`: `DECK_VARS` + `resolve()`. The deck names a machine-specific path `$VAR` and
  `run()` substitutes it, so what is built, logged, frozen and diffed stays portable. `make doctor`
  fails when a declared variable is unset.
- `scripts/lint.py`: `deck_portable` refuses an absolute include path in a frozen deck.
- CLAUDE.md rules 1 and 2, `doc/benches.md` and `doc/environment.md` state both rules.

## v1.00 — first tagged release

The template as it stood on 2026-09-09: the harness lifecycle (`certify` / `freeze` / `baseline` /
`check`), the ngspice lane wrapper, the ledger and context pack, the `deck_rebuild` and
`spec_quotes` lints, the linked agents and skills, the layout and sign-off stubs, and the docs
skeleton. A design cut before this tag can record `1.00` and update from there; its first update
may raise conflicts a human resolves rather than overwrite what the design changed.
