# CLAUDE.md — <design name> (agentic-design template)

**Map, not manual.** This file routes; the docs hold the substance. Instantiating: `make init`
first (needs `SX_ROOT` = the SpiceXplorer workspace checkout), then replace every `<…>`, fill `harness.yaml`, rename the design package (`git mv design <name>`, then `package:` in
`harness.yaml`, the imports, `Makefile`, `experiments/_template/`; **re-sign** whatever was already
signed — its row hashes the old scorer path), delete this sentence.

## Mission

<One paragraph: the block, the PDK and supply, the headline number to beat and the yardstick.> The
spec of record is `doc/target-spec.md`, its machine twin `spec:` in `harness.yaml` (`make lint`).

## Read this before that

| you are about to… | read first |
|---|---|
| set up a fresh checkout | `make init` — needs `$SX_ROOT` (the SpiceXplorer workspace); links `.sx/platform`, initialises the `.sx/skills` library and the agent/skill links, syncs the venv. `doc/environment.md` has the rows |
| anything | `doc/target-spec.md` — the acceptance box, pass/fail definitions |
| measure something | `doc/benches.md` — reference-first, and the measure → spec-key map |
| touch the DUT / model it | `doc/design-reference.md` — device map, validated model, the constraints every candidate respects |
| pick a paper / technique | `references/INDEX.md` (cite by handle) |
| run simulations | `design/` module docstrings + `doc/environment.md` (lanes, gotchas) |
| draw a layout | `layout/` (the generator) + `.claude/skills/layout-evidence/SKILL.md` |
| report a result you want believed | `signoff/README.md` — the design of record, one directory per simulation fidelity |
| start an experiment | copy `experiments/_template/`; name its phase; add one row to `doc/experiment-log.md` |
| verify someone's claims | `doc/reviews/README.md` — the verifier's report shape |
| learn from / add a lesson | `doc/journal.md` (index) + one file per entry in `doc/journal/`; `doc/memory/README.md` has the four tiers, the write-risk ordering and supersede-never-delete |

## How the work is organized

**Five phases, and every experiment names the one it belongs to.** They are not gates — a topology
question reopens at sizing often enough — but the name tells the next agent what kind of evidence
it is reading, and it is the first column of `doc/experiment-log.md`.

| phase | the question it answers | what it usually produces |
|---|---|---|
| `system` | what must this block do, and how will we know? | the spec table, the budgets, a behavioural model |
| `topology` | which circuit can do it at all? | candidates ranked, and the measurement that ranked them |
| `sizing` | which device sizes meet the box? | a sizing point, corners, mismatch |
| `improve` | can the topology itself do better? | a variant that beat the incumbent, and by how much |
| `layout` | does it survive being drawn? | the generator, GDS, DRC/LVS, post-extraction numbers |

## Where things go

**Work freely inside the repo, never beside it.** Open as many experiment directories as the work
needs — that is what they are for. What is not free is where the output lands: every derived
artefact has one home, and raw simulator output has none, because it is not committed at all.

| what you just made | where it goes |
|---|---|
| an exploration, a sweep, an A/B | `experiments/NNN-<slug>/` — `run.py` simulates, `README.md` states the verdict |
| the figure or table carrying its claim | `experiments/NNN-*/figs/`, `.../tables/` |
| a measured result, with its conditions, that you want believed | `signoff/<fidelity>/` — `signoff/README.md` lists the fidelities |
| the netlist and schematic of record | `signoff/schematic/` |
| GDS, DRC and LVS reports, the extracted netlist | `signoff/layout/` — the generator itself stays in `layout/` |
| a lesson worth reusing | one file in `doc/journal/`, one line in `doc/journal.md` |
| a paper, datasheet or standard | `references/` + a row in `references/INDEX.md` (cite by handle) |
| working notes, throwaway scripts, a plot you just want to look at | `experiments/NNN-*/out/` — inside the repo and git-ignored. **Not** `/tmp`, and not the agent tool's own scratchpad |
| rawfiles, work directories, simulator logs | the scratch root (`$SX_SCRATCH`) — never the repo |

`artifact-home` in `scripts/lint.py` enforces the table: a committed `.png`, `.csv`, `.pdf` or
`.gds` outside a declared home fails `make lint` with the fix. **The reason is not tidiness.** A
reviewer who cannot find the evidence treats the claim as unsupported, and six weeks later so does
the agent that wrote it.

**It is not a straitjacket either.** `experiments/` is wide open — organize inside it however the
work wants — and a design with its own durable output directory (a physics lane, a report tree)
adds one line to `ARTIFACT_HOMES` saying what lives there. What the check refuses is the
undeclared case: an artefact somewhere nobody wrote down.

## Harness commands (`make help`; the generic work is `spicexplorer-harness`, driven by `harness.yaml`)

- `make doctor` — is the lane alive? A one-resistor deck through `design/sim.py`, passing only on a
  parsed scalar + rawfile + the per-run `.spiceinit` (`doc/environment.md`). `make test` covers the
  generic modules and the scorecard lifecycle (live tests skip without ngspice); `make lint` the
  repo invariants `harness.yaml` drives — every failure message carries its fix.
- `make pack K="noise irn"` — **working memory** at task start; re-run with `S="<failure
  signature>"` before diagnosing anything new. `make runs ARGS="--fails | --best <metric> | --exp
  NNN"` reads the ledger every `metrics.evaluate()` appends to.
- `make template-status` / `make template-update` — this repo was **copied** from the template, so
  it records the release it was cut from in `.sx/template-version` (`#.##`) and takes later MINOR
  work by three-way merge, never by overwrite (`CHANGELOG.md` says what each release changed; a
  MAJOR release is refused and its migration note printed). Read every merged hunk, then
  `make lint && make test`. The shared agent/skill library moves separately: `make skills-update`.
- `make certify` / `make freeze` / `make baseline` / `make check` — write the reference and sha-lock
  it, print it, prove it still reproduces. `ARGS="--author X --verified-by Y"` signs it; unsigned
  deliberately carries no provenance block, and `--certify` writes nothing if a bench failed. Until
  `reference_scorecard:` names one **`make check` SKIPs (exit 0): a no-op, not a pass**. What it
  freezes is what `metrics.run_decks` produced — a deck's own printed scalars plus
  `<package>/bench.py`'s reduction — so any number your benches post-process belongs in that module
  before you certify (rule 1).

## Simulation lanes and reuse (contract for every agent in this repo)

- **Open-source PDK (IHP SG13G2, sky130, gf180 …) → the open lane.** ngspice (with OSDI/openvaf models) through this repo's lane
  module (`design/sim.py`), KLayout / magic / netgen / kpex for layout and sign-off, xschem for schematics — natively
  on the workstation; `make doctor` proves the lane. An open-PDK bench is never routed through the commercial tools.
- **Commercial PDK under NDA → the bridge lane only, through the platform's bridge-lane package.** Those simulations
  run on the EDA server through the lab's remote-simulator bridge; the reusable half of that lane is a platform leaf
  package whose name is `spicexplorer-` plus the simulator's name (`lane.run_deck` for deck text, `lane.run_dir` for a
  whole netlist directory, `results`, the `doctor` probe, and a launcher callable exactly like the simulator binary).
  This repo's `design/sim.py` WRAPS it — the repo's policy only: where runs go, which env vars, the mode, the doctor's
  expected keys — and never carries a private bridge driver, so a lane bug is fixed once, in the platform, for every
  design. Depend on that package (see `pyproject.toml`); do not name the bridge yourself — the platform pins it. The
  skill library's opt-in `<simulator>-lane` skill has the API table and a wiring snippet. Decks are built here,
  uploaded by basename with *relative* `include`s, simulated there, and only results come back. Kit bytes never reach
  the workstation or the model — anything under `/CMC` asks for the person's permission (the one hook); every
  server-side artifact is design-named, never tool-named.
- **A model library that lives only on some machines is named in a deck by variable, never by path.**
  The deck text writes `$VAR`, `<package>.sim.DECK_VARS` declares it, `sim.run` resolves it against
  this machine as the deck is handed to the simulator, and `doc/environment.md` pins WHICH library by
  its revision name. Everything else — the builder, the ledger row, the frozen reference, `git diff`,
  the `deck-rebuild` and `deck-portable` lints — sees portable text, which is the only reason a
  certified deck can be committed at all. Redacting on write and restoring on read does not work:
  the rebuild check compares bytes.
- **SpiceXplorer first.** Before writing a script, use what exists and compose it (HOW to run it: the `spicexplorer-tools`
  skill — what this pyproject names runs in this venv with `uv run --no-sync`; any platform tool runs from
  `.sx/platform/.venv/bin/<script|python>`; never `uv run --project .sx/platform` without `--no-sync`): the platform packages
  (`spicexplorer_core` — `spice_engine.run_deck`, measurements; `spicexplorer_harness` — ledger, pack, lint,
  spec; `spicexplorer-optimize`; `spicexplorer_gmid`; `spicexplorer_layout` + `spicexplorer_signoff`;
  `spicexplorer_waveview`; `spicexplorer_circuitgraph`; `spicexplorer_netlist2xschem`), the orchestration
  workflows and MCP tools (`spicexplorer_orchestration.workflows`: layout, sizing, campaign, sign-off,
  literature), and the reusable agents and skills in `.sx/skills` (the lab's `analog-skill-directory`). A missing function is added to the platform or the
  library by PR (gap-as-signal), never reimplemented privately in this repo.
- **Visual evidence and reports.** Every design cell and every testbench has a **human-readable xschem
  sheet** (the `schematic-of-record` and `testbench-schematic` skills): generated from the certified netlist with `spicexplorer-netlist2xschem`, proven equal
  to it, PNG render committed — never a hand drawing offered as a schematic. When a cell must live in the
  commercial schematic editor it is **ported from that sheet** through the bridge's `xvport` lane and
  re-proven identical with `circuitgraph`. Findings are **tables or plots regenerated from simulated
  data** with the spec boxes drawn (the `findings-as-plots` skill); a simulation report is one `experiments/NNN-*/` directory —
  `run.py` simulates into git-ignored `out/*.json`, figures land in committed `figs/`, `mk_readme.py`
  rewrites its README from `out/` — or this repo's documented equivalent, so no number is typed into prose.

## Rules (mechanically enforced where possible; the rest is contract)

1. **Reference first.** A number that has not passed the frozen definitions is a claim. The code
   that turns a simulated waveform into that number — phase margin from an AC sweep, settling time
   from a step; the bench's **reduction** — lives in the PACKAGE (`<package>/bench.py`: `PRODUCES` +
   `reduce()`), never only in an experiment: `make certify` freezes what `metrics.run_decks` produced, so a phase margin, a
   crossover or a settling time computed inside an `experiments/NNN-*/run.py` is a report, not a
   reference — nothing to freeze, nothing for `make check` to reproduce. One function, both callers.
2. **Decks are built, never text-edited, and portable.** A sizing point is a `<package>.dut.Design`
   and every bench deck is generated from it; frozen dirs are sha-locked and must still rebuild.
   A deck is a document before it is a simulator input, so no machine-specific absolute path may
   appear in one: the deck text names `$VAR`, `<package>.sim.DECK_VARS` declares it, and `sim.run`
   resolves it as the deck is handed to the simulator (`deck-portable` lint). Redact-on-write with
   restore-on-read is not an alternative — `deck-rebuild` compares bytes and every redacted bench
   stops reproducing.
3. Every experiment: **falsifiable hypothesis first**; a control whenever a knob moves.
4. Findings are **tables or plots** regenerated by a committed script (`run.py` simulates,
   `mk_readme.py` rewrites the README from `out/*.json`); a number typed into prose drifts.
5. **Parallelize batches** (`spicexplorer_harness.batch(items, fn, env=H.jobs_env)`, or
   `design.exp.run_batch(designs, score)`; the width env var is `jobs_env` in `harness.yaml`).
6. **Clean provenance.** Reference the PDK by name, pin its version in `doc/environment.md`, never
   vendor model bytes. `denylist:` in `harness.yaml` is a build failure, not a style note.
7. **Designer ≠ verifier.** Claims are re-measured from raw artefacts and signed by a second actor
   (`verifiers:`); the report lands in `doc/reviews/`.
8. **Gap-as-signal.** If you struggle, fix the harness and journal it. Before recording a gate as
   "waiting on X", do X once and watch it go green. A defect or gap in the *framework* (a platform tool, a lane,
   a harness gate, a linked skill or agent) goes back to its repo **at confirmation time** — the `sx-contributing`
   skill: quick fix (one concern, ≤ ~50 lines, test fails-before/passes-after) → PR now; anything bigger, and every
   new or changed agent/skill definition → a descriptive issue on the owning repo first (labels `found-by-agent`,
   `proposal:skill`/`proposal:agent`; members hold `triage` on the framework repos, so `--label` applies).
   **This template's repo is public**: an issue or PR there names no commercial kit, NDA-lane detail, member design
   or measured result — file such a template matter on the private design directory (`[template]` prefix) instead.
   Bitten twice → propose the lint. The local workaround is minimal and carries
   `# GAP: MacAnalog/<repo>#<n>`. Doing something a second design would repeat → propose the skill or agent that
   removes the repeat, even though nothing is broken.
9. **Sim economy.** Expensive runs only after the cheap scorecard passes the box.
10. **Write-risk ordering.** Episodic writes are automatic; semantic writes need provenance;
    procedural writes (`design/`, `scripts/`, agent defs, this file) are human-reviewed — agents
    propose diffs, never self-apply them.

## Agents and methods

The shared definitions are **links** into `.sx/skills` (the lab's `analog-skill-directory`, a
pinned submodule): never edit a linked file in place — change it in the library by PR and bump the
pin (`make skills-update` moves the pin to the library's main and re-links; commit what it stages — do it at the
start of a session when `make status` in the design directory says the design's skills are behind); a design-specific agent is a plain file beside the links. In `.claude/agents/` (each starts
from `make pack`, reads `harness.yaml`, obeys rules 7–10):
`paper-analyst` (paper → falsifiable brief; never simulates), `variant-runner` (parallel batches),
`signoff-verifier` (re-measures independently, signs the row), `schematic-builder` (the `.sch` of
record), `gardener` (report-only, by design). Visual evidence is not optional: `.claude/skills/` —
`schematic-of-record`, `testbench-schematic` (components, not text), `findings-as-plots` (spec
boxes on figures), `layout-evidence` (brief → generator → GDS → DRC/Jmax/LVS/PEX → review, via the linked
`layout-*` agents) — say how each is produced and gated. Also linked: `gmid-sizing`,
`current-mirrors`, `layout-annotation`, `neutral-artifact-naming`, and the bridge's two
remote-simulator skills (the `denylist:` keeps their vendor names out of this file).
A request for a schematic means the xschem sheet of record built by `schematic-of-record`
(never an ad-hoc drawing); only a cell already ported through the bridge's `xvport` lane is shown
from its ported cellview instead.

## Parallel sessions, blast radius, git

One experiment = one session = one worktree on `feat/NNN-<technique>`; `EXP=NNN` stamps the ledger.
A worktree is a new checkout: run `make init` in it (`.sx/platform` is git-ignored and `.sx/skills`
needs its submodule update) before `uv sync` can resolve the platform packages.
Ledger and work dirs are per checkout; shared docs (`doc/journal.md`, `doc/experiment-log.md`,
`references/INDEX.md`) are written at close-out only — until then write into your own
`experiments/NNN-*/README.md`. Branch `feat/<name>` off `main`, PR, squash. **Ask before pushing.**
Never commit `runs/`, work dirs, rawfiles or PDK content.
