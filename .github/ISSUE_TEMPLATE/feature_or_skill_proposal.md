---
name: Feature, skill or agent proposal
about: A capability the framework should grow — a platform function, a lint, a lane option, or a new/changed agent or skill definition. Every agent/skill definition change starts here (procedural writes are proposed, then human-reviewed); attach the PR once the prototype is proven on one design. See the `sx-contributing` skill.
title: "<area>: <one-line proposal>"
labels: enhancement
---

## Problem it removes
<!-- the repeated work, measured: "every OTA design re-derives the stb margins from the raw PSF by hand" -->

## Proposal
<!-- feature | skill | agent — name, inputs, outputs, where it lives, which existing skills/functions it composes -->

## Reuse evidence
<!-- which designs would use it now; where the local prototype lives (a design-local .claude/skills/<name>/SKILL.md, an experiments/NNN script, …) -->

## Acceptance
<!-- what a reviewer runs to say it works -->

## Alternatives considered
<!-- including "keep doing it by hand" and why not -->

- [ ] Labelled `proposal:skill` / `proposal:agent` if it is a definition; `found-by-agent` if an agent is filing
- [ ] No NDA content: no kit bytes, no kit-tree path, revision names only
