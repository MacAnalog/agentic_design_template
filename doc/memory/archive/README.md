# Memory archive

KIND: REFERENCE (what `doc/memory/archive/` holds, and how an entry moves here)

An entry in this directory stays indexed and is no longer loaded. `harness.yaml` lists
`doc/memory/archive` in `memory.dirs`, so `make lint` still wants its row in `doc/journal.md` and
checks its header. It is not in `memory.load_dirs`, so `make pack` does not serve it.

## What moves here

| entry | where it goes |
|---|---|
| **live, and needed at most task starts** | stays in `doc/journal/` |
| **live, rarely needed** (a workaround for one bench, a lesson about a retired topology) | here, with `status: live` unchanged |
| **superseded** (the three-place edit of `doc/memory/README.md` §4 done) | stays where it is: the pack already skips it, and its index row is not charged to the cap |

Move entries here when `make lint` warns that the bare pack dropped lessons to fit
`memory.pack_budget`. A bare pack lists lessons newest first, so the dropped ones are the oldest.
An archived entry is also left out of `make pack K="…"`, so archive only what no task needs by
default.

## How to move one

1. `git mv doc/journal/<slug>.md doc/memory/archive/<slug>.md`. The file name stays the same, so
   the index row still matches it.
2. In `doc/journal.md`, change the row's link to `memory/archive/<slug>.md`. Leave its type and
   status as they are.
3. `make lint` (the entry is still accounted for) and `make pack` (it is no longer listed).

An archived entry is never deleted (supersede, don't delete: `doc/memory/README.md` §4). To load
it again, move it back and restore the link.
