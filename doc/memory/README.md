# The memory model

KIND: REFERENCE

Four memory tiers (CoALA, arXiv:2309.02427, as distilled in the workspace plan
`plan_harness_engineering.md` §4e), each with a physical home in this repo, a declared writer,
and a declared write risk. The governing constraint:

> **No memory surface may grow past what fits comfortably in an agent context.**

One file per entry, a small lint-enforced index, a size cap per surface, and the overflow
dirs below all exist to satisfy that rule. A memory you cannot load is not a memory.

## 1. The tiers

| tier | home | written by | read by |
|---|---|---|---|
| **working** | assembled fresh: `make pack K="…"` | retrieval over the tiers below | the agent, at task start and again on every new symptom (`S="…"`) |
| **episodic** | `runs/ledger.ndjson` — one row per simulation, gitignored, per checkout | **automatic**: `lab.metrics.evaluate()` via `spicexplorer_harness.log_run` | `make runs`, the pack's Episodes section |
| **semantic** | `doc/journal/` (one file per lesson) + `doc/journal.md` (index); overflow in `doc/memory/semantic/`; curated docs `doc/design-reference.md`, `doc/pdk-notes.md`, `pdf/INDEX.md`, experiment READMEs | distillation at experiment close-out, or the moment a failure surprises you; **provenance required** | the pack's Lessons/Constraints/Papers sections |
| **procedural** | `lab/`, `scripts/`, `Makefile`, `harness.yaml`, agent definitions, `CLAUDE.md`; recipes in `doc/memory/procedural/` | **human-reviewed only** (trap → gate promotion) | `CLAUDE.md` harness commands |

## 2. Learning actions

1. **experience → episodic.** Automatic. Never hand-edit the ledger; a hand-edited flight
   recorder is not evidence. A later contradicting row revokes an earlier sign-off.
2. **distillation → semantic.** Read the episodes, write the entry with provenance: ledger
   tags, experiment dir, deck hash, paper equation. A claim with no pointer back is an opinion.
3. **new code → procedural.** A trap that recurs becomes a lint (`scripts/lint.py` EXTRA), a
   `lab/` helper, or a deck-builder invariant. Agents propose the diff; an owner applies it.

## 3. Write-risk ordering

> episodic (automatic) → semantic (agent-written, provenance, supersede-don't-delete) →
> procedural (human-reviewed only). No agent ever edits its own decision procedures.

## 4. Entry format and supersession

Entry file: `# YYYY-MM-DD — title`, blank line, `KIND: journal entry | type: semantic|procedural
| status: live`, body. Filenames are slugs (code may cite them), the date lives in the title.
Retiring an entry is a three-place edit: `status: superseded` in the header, a
`[superseded <date> — see …]` note as the first body line, and `**superseded**` in the index
row. The pack serves only live entries. Retire the claim that died, not the whole entry.

## 5. Blast radius

One experiment = one worktree; the ledger and work dirs are per checkout; `EXP=NNN` stamps
rows. Shared docs are written at close-out, from the experiment's own README.

## 6. Enforcement

`make lint` (`spicexplorer_harness.lint`): every entry indexed, typed, dated, under the size
cap, supersession complete; every experiment dir logged with Paper/Hypothesis/Verdict rows;
every PDF indexed; spec numbers present in `doc/target-spec.md`; frozen dirs match their
`SHA256SUMS`; the denylist is clean; the pack retrieves at least one constraint and one lesson.
