# 2026-09-01 — a trap that bites twice becomes a lint

KIND: journal entry | type: procedural | status: live

When an agent struggles — a missing tool, a doc it could not find, a check that would have
caught the mistake — the struggle is the signal, not the agent. Fix the harness: add a
`def check(L: Lint)` to `scripts/lint.py` `EXTRA` whose failure text teaches the fix, add the
`lab/` helper, or add the doc line the pack could not retrieve. Then record it here with the
ledger tag or experiment that exposed it.

Procedural write (scripts/, lab/) — proposed as a diff for owner review per CLAUDE.md rule 10.
