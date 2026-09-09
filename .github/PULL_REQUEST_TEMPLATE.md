<!-- Merge report: this body becomes the squash commit. Jot points; every strong verb ("validated", "green") backed by a
     gate you ran and read. Head branch must be feat/<name> (branch-guard). Quick fix ≤ ~50 lines / one concern / a test
     that fails before and passes after — anything bigger starts as an issue (sx-contributing skill). -->

## What was done
- <artifact>: <one change per line; proof or number at the end>

## Assumptions
- <defaults chosen, specs inferred, scope drawn — or delete the section>

## Errors / setbacks / gotchas
- <found by <design> experiment NNN: how; pre-existing vs introduced labelled — or delete the section>

## Next Steps
- <follow-up this PR sets up, or "none — closed">

Closes #<issue>  <!-- when it closes one -->

- [ ] Gate run locally and read (which: `make check` / `uv run pytest -q packages/<pkg>` / `bin/sx-link --check`)
- [ ] No NDA content in diff, message or branch name: no kit bytes, no kit-tree path, revision names only
