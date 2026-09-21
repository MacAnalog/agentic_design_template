# agentic-design-template

A starting point for an agent-first analog design repo. The parts every design shares — run
ledger, lints, context pack, spec checks — come from the SpiceXplorer platform package
`spicexplorer-harness`. This repo holds only what is specific to one design: `harness.yaml`,
the docs under `doc/`, the `design/` code that builds decks and measures them, and the agent
definitions and method notes under `.claude/`.

## Instantiate

1. `export SX_ROOT=<your spicexplorer-workspace checkout>` (the lab's `~/.sx_env` does this), then
   get the tree. Prefer `make new` in `macanalog-design-directory`: it names the repo by the lab
   convention, creates it from the template on GitHub, clones it and runs the `make init` of step 2
   for you. Otherwise copy the tree by hand.
2. `make init`: it links `.sx/platform -> $SX_ROOT/spicexplorer-platform`, initialises the
   `.sx/skills` library (analog-skill-directory) with its agent/skill links, and runs `uv sync`.
   Repeat in every new checkout or worktree.
3. Fill `harness.yaml`, `pyproject.toml` (name, description) and every `<…>` in `CLAUDE.md`
   and `doc/`.
4. Rename the design package: `git mv design <name>`, set `package:` in `harness.yaml`, and
   update the imports plus `Makefile` and `experiments/_template/`. The package is named for the
   DESIGN — the instances are `ldo/` and `mzm_tx/`. `make lint` checks the package is importable;
   `layout/signoff.py` and `scripts/lint.py` resolve it from `package:` and need no edit.
5. The harness, core and waveview are editable path dependencies through `.sx/platform`
   (`make init` made the link; a read-only `SX_ROOT` is fine). A design that pulls in a further
   `spicexplorer-*` member names it in both `dependencies` and `[tool.uv.sources]`, then runs
   `uv sync` once.
6. `make doctor` must report the lane alive: it runs a one-resistor deck with a per-run
   `.spiceinit` through ngspice, driven by `design/sim_ngspice.py` — this repo's policy layer over
   the platform's `run_deck`, and what `design/sim.py` re-exports while `lane:` is absent. A
   commercial-PDK design instead sets `lane: bridge` in `harness.yaml`, fills in `design/pdk.py`
   (`REVISION`, `SECTIONS`, the two variable names) and adds the bridge-lane package to
   `pyproject.toml`; its `make doctor` runs the same probe on the EDA server. Then implement `design/dut.py` (`benches()` + `deck(bench)`) and
   `design/metrics.py`'s `KEYMAP`. `make test` covers the generic modules and the scorecard
   lifecycle.
7. `make certify` (add `ARGS="--author X --verified-by Y"` once a second actor has re-measured it),
   add the dir to `frozen:` and the scorecard to `reference_scorecard:`, then `make freeze`.
8. `make lint` must pass before the first experiment. `make guard` is the one command that runs it
   with `make test` and a clean-tree check before a push; `make hook-install` is the recommended
   per-clone step that attaches it to `git push` (see below).
9. For the layout lane, uncomment the `spicexplorer-gmid` / `-layout` / `-signoff` sources in
   `pyproject.toml` and `uv sync`.

## Before you push

The workflow is `feat/<name>` branch → PR → squash (CLAUDE.md, "Parallel sessions, blast radius,
git"). `make guard` is what makes it safe to automate: it refuses unless the tree is clean — both
`git diff` and `git diff --cached`, because staged-but-uncommitted is exactly the window a
`&&` chain slips through — and `make lint` and `make test` are green, printing one `REFUSING:` line
naming the clause that failed. `GUARD_SKIP_TEST=1 make guard` drops only the test clause and says
so, for a design whose suite is too slow to sit in front of every push.

`make hook-install` installs a `pre-push` hook that runs it (`make hook-remove` uninstalls). It is
**opt-in — `make init` does not install it** — because a hook that blocks ordinary work gets
removed, and the only hook this repo ships by default is the NDA kit-tree ask-hook, which asks
rather than blocks. The hook honours `core.hooksPath`, never overwrites a `pre-push` you wrote,
and its refusal names both deliberate bypasses (`git push --no-verify`, `GUARD_SKIP_TEST=1 git
push`). Linked worktrees share the hooks directory, so one install covers every worktree of the
clone. `make lint` reports whether the hook is there as an INFO line; it is never a failure.

## Repository map

Three kinds of directory, and the difference between them is the whole organizing idea:
**`experiments/` is where work happens, `signoff/` is what survived it, and `doc/` is what was
learned.** Everything else is plumbing.

| path | what |
|---|---|
| `harness.yaml` | the design described to the harness: spec rows, frozen dirs, denylist, ledger columns |
| `CLAUDE.md` | the entry map agents read first — including "Where things go" |
| `doc/` | target spec, design reference (constraints), benches, environment, experiment log, journal + index, `reviews/` (verifier reports), the memory model |
| `design/` | this design's own code. Yours to write: `dut` (sizing point → deck), `metrics` (measure, check, log), `bench` (the reductions). Generic, imported as-is: `sim` (the lane dispatcher — `lane:` in `harness.yaml` selects `sim_ngspice`, the default policy layer over `spicexplorer_core.spice_engine.run_deck`, or `sim_bridge` + `pdk` for a commercial kit simulated on the EDA server), `exp` (labelled batches, markdown, CSV), `plot` (spec boxes). Data stimulus and eye metrics are the platform's — `spicexplorer_waveview.stimulus` / `.eye` — imported directly by the designs that send symbols |
| `experiments/NNN-*/` | one directory per hypothesis, tagged with its phase; `_template/` is the shape — `README.md`, `run.py` (simulates into git-ignored `out/`, committed `figs/` and `tables/`) and `mk_readme.py` (regenerates the README from `out/*.json`) |
| `signoff/` | the design of record, one directory per simulation fidelity (`prelayout`, `postlayout-pex`, `postlayout-em`, and whatever physics a design adds) plus `schematic/` and `layout/`. `signoff/README.md` is the index: what is signed off, at which fidelity, by whom, when |
| `layout/` | the layout **as code**: `gen_cell.py` (generator contract, `LayoutParams`, the per-net obstacle map) and `signoff.py` (build → render → DRC → current density → LVS → PEX → the cell's own benches). Its output lands in `signoff/layout/` |
| `references/` | papers, datasheets and standards + `INDEX.md` (cite by handle, never by filename) |
| `tests/` | `make test`: the generic `design/` modules (the live-lane test skips without ngspice) |
| `scripts/lint.py` | repo-specific checks on top of the harness — including `artifact-home`, which keeps the map above true |
| `scripts/clean_runs.py` | `make clean-runs` (sweep the run dirs whose reduction is recorded and whose log has gone cold) and the scratch report `make doctor` prints |
| `scripts/githook.py` | `make hook-install` / `make hook-remove`: the opt-in `pre-push` hook that runs `make guard` |
| `notebooks/` | executed in place by `make notebooks`, outputs committed |
| `.sx/` | the per-checkout plumbing `make init` sets up: `platform` (git-ignored link to `$SX_ROOT/spicexplorer-platform`) and `skills` (the `analog-skill-directory` submodule: shared agents, skills, guard hooks, `bin/sx-link`) |
| `.claude/agents/` | links into `.sx/skills/agents/`: variant-runner, signoff-verifier, schematic-builder, paper-analyst, gardener + the layout chain (brief-author, designer, reviewer, schematic-codesign); design-specific agents are plain files beside them |
| `.claude/skills/` | links into `.sx/skills/skills/`: the visual-evidence methods (schematic of record, testbench schematics, findings as plots, layout evidence), `design-writing` (every document this repo produces), gm/ID sizing + LUTs, current mirrors, layout annotation, neutral naming, the remote-simulator learning journal and the bridge's two simulator skills |
| `.claude/settings.json` | the one hook (`.sx/skills/hooks/cmc_ask_hook.py`): anything under the NDA kit tree asks for permission; nothing else is blocked (owner ruling 2026-09-07) |
| `runs/` | `ledger.ndjson`, git-ignored; the numbers worth keeping move into experiment READMEs and `signoff/` |
| *(the scratch root)* | rawfiles, run dirs and simulator logs — `$SX_SCRATCH`, never the repo. A raw record is scratch, not evidence: reduce it, commit the reduction, `make clean-runs` |
