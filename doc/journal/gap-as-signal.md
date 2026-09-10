# 2026-09-01 — a trap that bites twice becomes a lint

KIND: journal entry | type: procedural | status: live

An agent that struggles has found something missing: a tool, a doc it could not find, or a check
that would have caught the mistake. The struggle is the signal, not the agent. Fix the harness:
add a `def check(L: Lint)` to `scripts/lint.py` `EXTRA` whose failure text states the fix, add the
`design/` helper, or add the doc line the pack could not retrieve. Then record it here with the
ledger tag or the experiment that exposed it.

Procedural write (scripts/, design/) — proposed as a diff for owner review per CLAUDE.md rule 10.
