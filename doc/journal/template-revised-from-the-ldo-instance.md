# 2026-09-04 — the template revised from what its first two instantiations had to add

KIND: journal entry | type: procedural | status: live

Two designs were cut from this template on the same day: an LDO and an optoelectronic
transmitter. Everything each of them had to add, work around, or discover is listed below with
the source that recorded it, and a decision: **absorb** (it ships here), **doc** (it ships as
guidance, not code), or **reject** (design-specific). The rule applied throughout: *if BOTH
instances independently added the same thing, it belongs in the template.*

Sources: the LDO repo `feat/001-reference` (`doc/journal/template-gaps-t8.md` — nine gaps recorded
at instantiation — plus its other 23 journal entries and `doc/reviews/review-002-capless-ldo.md`),
the transmitter repo `feat/003-integrate` (`doc/journal/`, `doc/reviews/review-003-resimulation.md`),
and the meta review `doc/reviews/overnight_build_2026-09-04.md`.

**23 absorbed, 5 as doc guidance, 9 rejected.**

## Absorbed as code or convention

| # | gap | source | where it landed |
|---|---|---|---|
| 1 | Both wrote a `certify()` / `--check` / `--baseline` lifecycle by hand | LDO + transmitter `metrics.py`, `scripts/baseline.py` | `design/metrics.py` + `make certify/baseline` |
| 2 | `certify()` wrote the tag under `provenance` and no hash block, so `scorecard-recompute` could not be greened by ANY signature | LDO `journal/a-signed-row-that-can-never-match.md` | `certify()` calls `harness.provenance()`, logs the signed row from the same block; a test proves the gate goes green |
| 3 | An unsigned scorecard with a provenance block is a lint failure with no remedy | same | the block is written **only** when `--author` and `--verified-by` are both given |
| 4 | `raw=SHA256SUMS` can never re-derive: `make freeze` hashes `scorecard.json` too | this pass | `certify()` writes a `decks.sha256` digest and points `raw=` at it |
| 5 | Both instances are multi-bench; the `Design` stub was single-deck | LDO `dut.py`, transmitter `deck.py` | `Design.benches()` + `deck(bench)` + `from_dict` round-trip |
| 6 | Both wrote a `deck_rebuild` lint extra | LDO + transmitter `scripts/lint.py` | ships generic, no-ops until something is certified |
| 7 | Both wrote a "the spec doc quotes the certified scorecard" lint extra | same (`spec_reference` / `scorecard_in_spec`) | ships as `spec_quotes`, format-tolerant |
| 8 | Drift tolerances were a hand-kept per-key table | LDO `metrics.TOL` | `drift_limit()` reads the spec row's own `tolerance:` band, `DEFAULT_RTOL` otherwise |
| 9 | Both wrote the same five vendor-name denylist rows | both `harness.yaml` | shipped (foundry names left to the instance) |
| 10 | Both used `ledger_columns` as a per-kind map because `metrics` logs `evaluate` + `bench` rows | both `harness.yaml` | shipped as the default shape |
| 11 | `spec_notes` was empty; both needed the same three shapes (report-only, off-nominal sign-off, what the reference is NOT) | both `harness.yaml` | the three shapes are commented in |
| 12 | Spec keys must be unit-scaled — the lint matches `f"{bound:g}"` literally in the prose | LDO template-gaps #2 | stated in `harness.yaml` beside `spec:` |
| 13 | The venv stops at simulation: gm/ID, layout and signoff all missing | LDO `journal/lab-venv-lacks-the-physical-lanes.md` | commented sources + the uv transitive-member rule in `pyproject.toml` |
| 14 | No layout scaffold at all | LDO `layout/` | `layout/gen_cell.py` + `layout/signoff.py` |
| 15 | Overlapping Metal1 merges into one legal polygon: a shorted net with DRC at 0 | LDO `journal/metal1-stub-shorts-are-drc-invisible.md` | the `Obstacles` per-net claim map in the generator skeleton |
| 16 | The DRC record crashed on its first REAL violation (unserialisable objects, in a line that only runs when the list is non-empty) | LDO `layout/signoff.py` comment, review-002 B1 attempt | `violation_counts()` + a test that feeds it a real violation object |
| 17 | Current density is nobody's check — the cell passed DRC, LVS, PEX and every bench 12–28× over the limit | LDO `journal/metal-current-density-is-nobodys-check.md` | a `jmax` stage over `spicexplorer_signoff.check_current_density`, and the gate in the layout skill |
| 18 | The LVS runner reports `matched=False` with an empty reason and the cause only in the log | LDO `journal/run-lvs-swallows-its-own-traceback.md` | `lvs()` copies the log tail in when the reason is blank |
| 19 | The post-layout row came from a tolerant local runner, not the frozen path | review-002 M4/M5 | `benches()` re-scores through `design.metrics.run_decks` |
| 20 | A hard-coded interpreter path (`~/…/envs/…`) for the generator lane | LDO `layout/signoff.py` | `$<PREFIX>_GDS_PYTHON` by the harness prefix rule, **no default**, error carries its fix |
| 21 | READMEs and figures were not regenerable; one generator lived under a git-ignored `out/` | transmitter `mk_readme.py`; both reviews | `experiments/_template/{run.py,mk_readme.py}` + rule 4 in `CLAUDE.md` |
| 22 | Both grew a `doc/reviews/` with no convention behind it | LDO `review-002`, transmitter `review-003` | `doc/reviews/README.md` |
| 23 | `lab/` was an inherited name that says nothing about the repo | owner decision, this pass | package renamed `design/`, `PACKAGE` + a `package_importable` lint check; instances rename it again |

## Absorbed as doc guidance only

| # | gap | source | where |
|---|---|---|---|
| 24 | The experiment-log lint matches the **directory name** verbatim; a bare `001` fails as "not listed" | transmitter `journal/lint-literal-dir-names.md` | `doc/experiment-log.md` header |
| 25 | The `_template` README's four labels must stay **bold row labels**; a heading of the same name does not pass | LDO template-gaps #7 | a comment in `experiments/_template/README.md` |
| 26 | The only available reference was not at the challenge's operating point | LDO `journal/reference-is-not-at-the-target-point.md`, template-gaps #8 | `doc/benches.md` + `doc/target-spec.md`: split the table, per row, into what the reference sets and what the literature sets |
| 27 | Every bound needs its origin, or nobody can tell which are negotiable | LDO `doc/target-spec.md` | a "where the bound comes from" column in the template's spec table |
| 28 | A red gate recorded as "waiting on X" that no reader could ever green | LDO `journal/a-signed-row-that-can-never-match.md` | `doc/memory/README.md` §6 + rule 8: demonstrate a gate goes green once |

## Rejected (instance-specific)

`lab/config.py` and the hand-written ngspice lane (already superseded by the consolidated
`design/sim.py` over the platform's `run_deck`) · the `KEYMAP` contents and `COLS` lists · the
`circuits/` directory shape and the circuit-database binding in `Design` · the LDO `TOL` values ·
`xschemrc` in `.gitignore` · the `psrr_1m` / `ac_loopgain_lo|hi` sign-off twins · the transmitter's
`physics/` lane and its model-parameter lints · `experiments/003-sizing/score.py` (an optimizer
objective; only one instance has one).

## Two gaps this pass could not close

1. **`package:` is not a `harness.yaml` key.** The loader rejects unknown keys and `Harness` has
   no such field, so the design package's name lives in `scripts/lint.py` as `PACKAGE`. Platform
   follow-up; the commented key in `harness.yaml` names it.
2. **The template ships no worked reference.** `make check` SKIPs and `deck_rebuild` returns early
   until a design fills `Design.deck`. Both are honest, but neither is exercised on the bare
   template by anything except `tests/test_design.py`, which builds its artefacts in a scratch
   repo. A tiny committed reference (one resistor divider, two benches) would exercise the whole
   certify → freeze → check → lint chain on arrival.
