# The memory model

KIND: REFERENCE

This repo carries four memory tiers (CoALA, arXiv:2309.02427, as distilled in the workspace plan
`plan_harness_engineering.md` §4e). Each tier has a home in the repo, a declared writer and a
declared write risk. The governing constraint:

> **No memory surface may grow past what fits comfortably in an agent context.**

One file per entry, a small lint-enforced index, a size cap per surface and the overflow
directories below all serve that rule. An entry that does not fit in the context is of no use.

## 1. The tiers

| tier | home | written by | read by |
|---|---|---|---|
| **working** | assembled fresh: `make pack K="…"` | retrieval over the tiers below | the agent, at task start and again on every new symptom (`S="…"`) |
| **episodic** | `runs/ledger.ndjson` — one row per simulation, gitignored, per checkout | **automatic**: `design.metrics.evaluate()` via `spicexplorer_harness.log_run` | `make runs`, the pack's Episodes section |
| **semantic** | `doc/journal/` (one file per lesson) + `doc/journal.md` (index); overflow in `doc/memory/semantic/`; curated docs `doc/design-reference.md`, `doc/pdk-notes.md`, `references/INDEX.md`, experiment READMEs, verifier reports in `doc/reviews/` | distillation at experiment close-out, or the moment a failure surprises you; **provenance required** | the pack's Lessons/Constraints/Papers sections |
| **procedural** | `design/`, `scripts/`, `Makefile`, `harness.yaml`, agent definitions, `CLAUDE.md`; recipes in `doc/memory/procedural/` | **human-reviewed only** (trap → gate promotion) | `CLAUDE.md` harness commands |

## 2. Learning actions

1. **experience → episodic.** Automatic. Never hand-edit the ledger: an edited row is not
   evidence of a run. A later contradicting row revokes an earlier sign-off.
2. **distillation → semantic.** Read the episodes, write the entry with provenance: ledger
   tags, experiment dir, deck hash, paper equation. A claim with no pointer back is an opinion.
3. **new code → procedural.** A trap that recurs becomes a lint (`scripts/lint.py` EXTRA), a
   `design/` helper, or a deck-builder invariant. Agents propose the diff; an owner applies it.

## 3. Write-risk ordering

> episodic (automatic) → semantic (agent-written, provenance, supersede-don't-delete) →
> procedural (human-reviewed only). No agent ever edits its own decision procedures.

## 4. Entry format and supersession

Entry file: `# YYYY-MM-DD — title`, blank line, `KIND: journal entry | type: semantic|procedural
| status: live`, body. Filenames are slugs (code may cite them); the date lives in the
title. Retiring an entry is a three-place edit: `status: superseded` in the header, a
`[superseded <date> — see …]` note as the first body line, and `**superseded**` in the index
row. The pack serves only live entries. Retire the claim that no longer holds, not the
whole entry.

## 5. Blast radius

One experiment = one worktree. The ledger and work dirs are per checkout, and `EXP=NNN` stamps
the rows. The session writes the shared docs at close-out, from the experiment's own README.

## 6. Enforcement

`make lint` (`spicexplorer_harness.lint`) checks that:

- every entry is indexed, typed, dated, under the size cap, and its supersession is complete;
- every experiment dir is logged, with Paper/Hypothesis/Verdict rows;
- every PDF is indexed;
- the spec numbers are present in `doc/target-spec.md`;
- frozen dirs match their `SHA256SUMS`;
- the denylist is clean;
- the pack retrieves at least one constraint and one lesson;
- the design package imports;
- a frozen deck still rebuilds;
- a signed scorecard still recomputes.

**A gate is only a gate once you have watched it go green.** Before recording a red check as
"waiting on someone to do X", do X once and look. A failure whose passing condition has never
been demonstrated may be unsatisfiable by anything a reader can do. It absorbs effort every time
it is re-read.
