---
name: Bug report
about: Something in the framework is wrong or missing and the fix is more than a quick PR (interface, lane, harness contract, more than one file family). A quick fix (≤ ~50 lines, one concern, a test that fails before / passes after) is a PR instead — see the `sx-contributing` skill.
title: "<area>: <one-line defect>"
labels: bug
---

## What happened / what was expected
<!-- one paragraph; the wrong number or message verbatim -->

## Where
<!-- repo@short SHA, package, file:line or function; workstation account, design that found it -->

## Reproduce
<!-- the exact command and a minimal input (a 10-line deck, a small JSON). No kit content, no kit-tree path. -->

## Impact
<!-- which gate/step it blocks; how many designs hit it; how you found it (design, experiment number) -->

## Workaround in place
<!-- the `# GAP: MacAnalog/<repo>#<n>` marked lines and their file — or "none, blocking" -->

## Proposed fix
<!-- what you would change, and why it is not a quick PR (interface / second opinion / more than one repo) -->

- [ ] No NDA content: no kit bytes, no kit-tree path, revision names only (`grep -n -e kits/tsmc -e crn65` on this text came back empty)
- [ ] Filed at confirmation time; the design's journal has the one-line entry with this URL
