# Template releases

KIND: REFERENCE (what each template version changed, and whether a design already under way can
take it)

A design is **copied** from this template, never submoduled to it, so it cannot pull. It records the
version it was cut from in `.sx/template-version` and takes later work with `make template-update`.
Versions are `MAJOR.MINOR`, written `#.##`:

- **MINOR** (`1.00` → `1.01`) — generic work: a module every design gets, a lint check, a hook in
  the lane, docs. It propagates into a design already under way. A file the design edited is merged
  three-way; where those edits meet the template's, the run leaves conflict markers for a human.
- **MAJOR** (`1.x` → `2.0`) — the scaffold's shape changed: a renamed module, a different
  `harness.yaml` contract, a lifecycle command that moved. `make template-update` refuses to cross
  one and prints the entry below instead; each MAJOR entry carries its migration steps.

`make template-status` prints the recorded version and the latest release. Releases are git
tags, `v<version>`.

## v2.13 — tests pass before `make init`, lint skips nested checkouts, the push hook clears `GIT_DIR`

Minor. No module is renamed; `harness.yaml` and `design/` are unchanged since v2.12, and the
`Makefile` changes only in the `skills-update` recipe, so every lifecycle command keeps its name.
The release is template#41 (merged as 3073686), a move of the `.sx/skills` pin and a check in
`make skills-update`: two new walk functions and a `main(repo)` entry in `scripts/lint.py`, one line
of the pre-push hook, one line of the `skills-update` recipe, 23 tests, one `CLAUDE.md` paragraph,
and 4 new agent and skill links.

- **`make test` passes on a fresh clone before `make init`** (template#41). The `sx_links` check
  reads state that only `make init` creates (the `.sx/platform` link and the `.sx/skills` links).
  Its test on the checkout itself therefore skips and names `make init` until init has run, and
  tests in temporary repositories cover its logic. `make lint` still reports `sx_links` as a
  failure before init, with `make init` as the fix.
- **A stale `uv.lock` now fails `make test`.** In a checkout where `make init` has run,
  `test_uv_lock_is_current_against_the_linked_platform` runs `uv lock --check --offline`. So
  `make test`, `make guard` and the pre-push hook fail once the linked platform changes the declared
  dependencies of a package the lock records. The fix is `uv lock`, then commit `uv.lock`.
  - The template's `uv.lock` records `pyyaml>=6.0` for `spicexplorer-core`
    (MacAnalog/spicexplorer-platform#284). It is current against platform `main` at 86ccc89 and at
    28a17f2. Against a platform older than that change, the test fails, and the `uv sync` inside
    `make init` rewrites the lock without `pyyaml`.
- **`make lint` skips nested checkouts** (template#40). The two checks that read every file below
  the repository root, `denylist` and the `scorecard.json` search, skip each directory that holds
  its own `.git`. An example is a second checkout of the repository made with `git worktree add`
  under `.claude/worktrees/`: its uncommitted files now fail only its own `make lint`.
  - **A whole-tree check a design adds** to `scripts/lint.py` walks with `own_tree_walk`.
  - **`scripts/lint.py` runs through `main(repo)`**, so a test can lint a fixture repository;
    `tests/test_lint_own_tree.py` (10 tests) is that test.
  - **`own_tree_only`** carries the template's half of the fix until the shared install runs a
    platform with MacAnalog/spicexplorer-platform#289. Its docstring names, one line per check, what
    that check reads. A new test in `tests/test_design.py` fails when a listed check imports a
    `<package>.<module>` that its line does not name.
- **The pre-push hook clears `GIT_DIR`, `GIT_WORK_TREE` and `GIT_INDEX_FILE`.** A push from a
  checkout made with `git worktree add` runs the hook with `GIT_DIR` set to that checkout's git
  directory. The `git init` and `git commit` calls that `make test` makes in temporary directories
  then wrote into the repository being pushed: in a throwaway clone, 8 commits, `core.bare=true`, a
  stray worktree and a branch.
  - **`tests/conftest.py`** clears the same three variables for the whole test session, so
    `make test` is also protected under a hook installed by an earlier release.
  - **2 tests in `tests/test_guard.py`** show that each of the two layers is needed.
- **`make skills-update` refuses to run before `make init`.** Before this release, `.sx/skills` in
  such a checkout had no `.git`, so the recipe's `git -C .sx/skills` fetch and checkout ran in the
  design's own repository and moved its HEAD from its branch to a detached `origin/main`. The recipe
  now exits 2 unless `.sx/skills/.git` exists (a file, for a submodule), and names `make init` as
  the fix. `tests/test_skills_update.py` (2 tests) runs the recipe in temporary repositories.
- **`CLAUDE.md`** gains one paragraph: the two whole-tree checks skip a nested checkout, and a
  whole-tree check an agent adds walks with `own_tree_walk`.
- **`.sx/skills` moves from de8d992 to e9c0230**, the `main` of MacAnalog/analog-skill-directory:
  28 commits, 27 of them on the library's first-parent line. The `design` link set gains 4 links
  and loses none; links go from 9 agents + 16 skills to 10 agents + 19 skills.

  | link | what it is |
  |---|---|
  | `.claude/agents/schematic-reviewer.md` | the reviewer of the schematic builder/reviewer pair (MacAnalog/analog-skill-directory#42) |
  | `.claude/skills/measurement-setup-of-record` | the measurement traps of the simulation lane, the harness and the experiment process |
  | `.claude/skills/analog-knowledge-authoring` | the standard a knowledge skill is written to (MacAnalog/analog-skill-directory#45) |
  | the skill for the commercial-simulator lane that `lane: bridge` selects | linked only on request before this move; now in the `design` set |

  - **Content changed** in 8 of the 9 agents and 13 of the 16 skills that were already linked.
  - **`sx-link --check`**, which `sx_links` runs, reports two more states once a design's own pin
    reaches e9c0230: WRONG, a link that resolves to another entry or another checkout, and LOCAL, a
    local file or directory with the name of a library entry, which keeps that entry from loading.

**Taking it:**

1. **`make template-update`.** Where the design edited them, it merges three-way: `CLAUDE.md`,
   `Makefile`, `scripts/lint.py` (every design that added a check to `EXTRA`), `scripts/githook.py`,
   `tests/conftest.py`, `tests/test_design.py`, `tests/test_guard.py` and `CHANGELOG.md`. It adds
   `tests/test_lint_own_tree.py`, `tests/test_skills_update.py` and the 4 links. It does not carry
   `uv.lock`, the `.sx/skills` pin or `doc/`.
2. **`make skills-update`**, then commit the pin. Until the design's `.sx/skills` reaches e9c0230,
   a new link whose entry its library does not have points at nothing: 3 of the 4 at de8d992, the
   template's previous pin. `make lint` does not report them, because the older link set does not
   list them. A design already at e9c0230 or later has the 4 links, and they merge without
   conflict.
3. **`make lint && make test`.** If the new `uv.lock` test fails, run `uv lock` (or `make init`,
   whose `uv sync` relocks) and commit `uv.lock`.
4. **`make hook-install`** again in each clone that installed the hook. The installed hook is a
   copy and keeps the earlier text until it is written again; until then, `tests/conftest.py`
   protects `make test`.

## v2.12 — the public bug template stops spelling a kit's revision token

Minor, one file, no design module touched. `.github/ISSUE_TEMPLATE/bug_report.md`'s NDA checklist
line used a real commercial kit's model-library revision token as its `grep` example. The token is
a kit identifier; this repository is public, so the line now tells the filer to grep the issue text
for their own kit's directory token and revision token instead. `make template-update` takes it as
any MINOR; a design that already edited its bug template gets the usual three-way merge.

## v2.11 — the deck says which models it needs, and the raw records stop piling up

Minor. Two gates and one sweep, all of them off by default in the sense that matters: the new lint
check is silent until a design fills one map, and nothing is deleted unless a ledger row says the
record has already been reduced.

- **`deck_models`, a new lint invariant** (template#36). A design moved one device to another
  model flavour — a two-line netlist edit — and two benches went on building their deck header
  from a fixed list of model groups that did not include the new flavour's section. `make lint`
  (20 invariants), `make test` (47) and `make guard` were all green, and the branch was pushed:
  nothing in this repo simulates, so the first thing that could see it was the simulator, whose
  verdict (`unresolved master`) reads like a typo in a device line rather than a missing include.
  The check builds every deck the design builds — the frozen `design.json` points `deck_rebuild`
  enumerates, plus `<package>.dut.REFERENCE`, so it works before the first certification — and for
  each model name in the new `<package>.pdk.MODEL_GROUPS` map that the deck BODY instantiates, it
  requires one of that group's section spellings (any corner) on an include line of the deck
  HEADER. It fails with the bench, the model, the missing group and the builder to edit.
  - **`MODEL_GROUPS: dict[str, str] = {}` in `design/pdk.py`** is the design-side map (model name
    -> `SECTIONS` group) the check reads. Empty is legal and is the shipped state: the check then
    prints one INFO line on `lane: bridge` and nothing at all on the open lane, whose models come
    from the PDK's own init file. It is never a warning — a check nobody can satisfy yet must not
    colour "all invariants hold".
- **`make clean-runs`** (template#37). One overnight campaign left **212 GB** of raw transient
  records in one account's scratch, every one of them already reduced to a committed table;
  nothing deleted them because nothing owned deletion — `make clean` removes a whole checkout's
  work dir (too coarse mid-campaign) and the lane never revisits what it wrote. The new sweep
  removes a run dir only when all of it holds: it sits directly under `<work>/runs/`, it carries
  no `.busy` marker, a ledger row names its label and is not a bare `sim_error`, and its simulator
  log has been cold for `AGE` hours (default 24). Everything else is printed with the reason it
  survived, so the output answers "why is my scratch still full?". `ARGS="--dry-run"` plans
  without deleting; `AGE=0` sweeps every reduced record once a campaign is over.
  - Matching is on the LABEL, never the hash: a run dir is `<slug(label)>-<sha256(deck)[:8]>` over
    the RESOLVED deck, while the ledger's `deck` column hashes the PORTABLE text — the two
    legitimately differ wherever `DECK_VARS` or a save list is in play.
  - It does **not** replace `spicexplorer-harness prune`, the platform's rawfile-level retention
    (`keep_raw:`, the `raws` ledger column, an orphan pass). That thins rawfiles inside runs you
    still want; this removes whole run dirs of this checkout. Use both.
- **`make doctor` reports scratch** — this checkout's work dir size and run count, with a warning
  above `$SX_SCRATCH_WARN_GB` (50 GB), so the designer hears it before the workstation admin does.
  The report runs whatever the lane probe said, and the probe's exit code is still what `make
  doctor` returns.
- **`scratch_budget`, a SOFT lint invariant** — `L.warn`, never `L.fail`: a work dir over the warn
  mark whose biggest run dirs have no reduction row. Scratch is a property of the machine, not an
  invariant of the design, and a gate that goes red because a campaign is in flight is a gate
  people switch off.
- **The rule, in `CLAUDE.md`**: *a raw simulation record is scratch, not evidence. Reduce it,
  commit the reduction, delete the raw. Keep a raw record only while its reduction has not been
  committed, or when the record is the thing under test.*

**Taking it:** `make template-update`; no conflicts expected unless you edited the `doctor:` or
`clean:` recipes, `design/pdk.py`'s head, or `scripts/lint.py`'s `EXTRA`. Nothing is deleted by
taking the release — `make clean-runs` only runs when you type it. A design on the sectioned lane
should fill `MODEL_GROUPS` while the benches are fresh in mind; until it does, the new check only
prints one INFO line.

## v2.10 — worktrees are ignored, and `make check` says WHY it is red

Minor, two small things, nothing changes for a design that has neither.

- **`.gitignore` excludes `.claude/worktrees/`** (template#33). An agent or session worktree is a
  real git checkout inside the repo; `git add -A` (or `git add .claude`, the natural thing to type
  when committing a skill or agent link) swept them in as embedded-repo gitlinks — a commit SHA and
  a path with no remote, meaningless to anyone who clones. Two landed and were reverted in one
  design in one session. The repo rule was already "never commit work dirs"; now there is a
  mechanism behind it.
- **`make check` propagates the harness's exit code** (`|| rc=$$?`, was `|| rc=1`). Since
  platform #217 `design.metrics --check` exits **3** when the gate COULD NOT RUN (nothing certified
  yet, or no frozen decks) and **1** on a real drift; folding both to 1 made an uncertified design
  read exactly like a drifted one to every `&&` chain and agent. A fresh design now exits 3 from
  `make check` until it certifies — that is the point, not a regression; `make baseline
  ARGS=--allow-skip` is the deliberate opt-out for the one legitimate case. If lint fails AND the
  check skips, the 3 wins: still nonzero, and it names the later failure.

**Taking it:** `make template-update`; no conflicts expected unless you edited `.gitignore` or the
`check:` recipe.

## v2.09 — the gates get something to be attached to: `make guard`, and an opt-in pre-push hook

Minor, and **nothing changes for a design that does not run `make hook-install`**: no hook is
installed by `make init` or by anything else, `make lint` and `make test` behave exactly as
before, and the only visible difference in a checkout that ignores this release is one extra INFO
line at the end of `make lint`.

`make lint && make test && git commit && git push` READS as conditional. Twice in one design it
was not (#31): the lint had been typed as a separate earlier command, was watched failing, and the
later chain committed and pushed anyway; the same shape later swallowed an entire experiment arm
whose launch sat behind a `&&` whose left side failed, so its absence read as a completed null for
hours. Both are one defect — a condition that is not attached to the consequential command. Every
design cut from this template carried it, so the fix ships here.

- **`make guard`** — one command that cannot be half-typed. It refuses unless: this is a git
  checkout; `git diff --quiet` AND `git diff --cached --quiet` both pass; `make lint` is green;
  `make test` is green. Each refusal prints exactly one `REFUSING: …` line naming the clause.
  `--cached` is checked separately on purpose — `git diff --quiet` alone passes on
  staged-but-uncommitted changes, which is precisely the window the guard exists to cover.
- **Clause order is tree, then lint, then test**, not the order the issue proposed. Lint and test
  judge the WORKING TREE, not the commit being pushed, so their verdict means nothing while edits
  are still loose; it is also the cheapest clause first. The lint/test output is NOT swallowed:
  a guard that hides which check failed forces a re-run to learn it.
- **`GUARD_SKIP_TEST=1`** drops only the test clause, for a design whose suite is too slow to sit
  in front of every push. It is not silent — the run prints that the clause was skipped
  deliberately, and the tree and lint clauses still apply.
- **`make hook-install` / `make hook-remove`** (`scripts/githook.py`) install and remove a
  `pre-push` hook that runs `make guard`. **`make init` does NOT install it, and this is the
  decision, not an oversight**: a hook that blocks ordinary work gets removed, so the hook that
  survives is the one its owner chose per clone. The hook is written to
  `git rev-parse --git-path hooks`, so `core.hooksPath` is honoured; it never overwrites a
  `pre-push` somebody else wrote (it reports and changes nothing); re-installing is idempotent.
- **The hook's refusal names its bypasses**, because a bypass that is hard to find gets replaced by
  deleting the hook: `git push --no-verify` skips it entirely, `GUARD_SKIP_TEST=1 git push` drops
  the test clause (git hands its environment to the hook, so the variable reaches `make guard`).
- **`make lint` reports the hook as INFO, never as a failure**, and `hook_info` is deliberately not
  a check in `EXTRA` — neither `fail` (it would block a repo over a per-clone convenience) nor
  `warn` (the run would still count it among the invariants it reports holding). Hook installation
  is a choice, not an invariant of the design, so the invariant list and the exit code are
  untouched.
- **Linked worktrees share the hooks directory**, so installing from one worktree guards every
  worktree of that clone — including a fresh one where `make init` has not run and `make lint` is
  therefore red. Documented in CLAUDE.md beside the one-experiment-one-worktree convention; it is
  the concrete case `--no-verify` is for.
- `tests/test_guard.py` drives the real recipe: a throwaway git repo gets this repo's own
  `Makefile` with stub `lint:`/`test:` recipes appended (make takes the last recipe), so every
  clause, the escape, install/remove/non-clobber, `core.hooksPath`, and a live
  `git push --dry-run` refusal are tested without rewriting the guard in the test.

## v2.08 — the commercial-PDK lane ships here, instead of being copied between designs

Minor. **A design with no `lane:` key is unaffected** — same lane, same behaviour, same
dependencies. What moved is a file name: the v2.07 `design/sim.py` is `design/sim_ngspice.py`,
which gained a `main()` entry point, a docstring paragraph and two edited comments, and nothing
that runs. Everything new is opt-in twice: the key, and the platform package a commercial-PDK
design adds to `pyproject.toml`.

The template shipped only the open lane, so every commercial-PDK design began by deleting
`design/sim.py` and hand-porting a neighbour's. Three designs in the lab's private directory now
carry near-identical copies of two files whose contract says "this repo's policy only" — and what
was actually being copied was the WIRING: `work()`, `run()`, `preflight()`, the kit-path
token/`restore()` mechanism, the revision pin. The copies had already diverged, so a lane bug had
three fixes; the wrapper had quietly become the private driver that the "wrap the platform package"
rule exists to prevent (MacAnalog/macanalog-design-directory#46).

- **`lane:` in `harness.yaml` selects the lane; `design/sim.py` re-exports it.** `ngspice` (the
  default, and what the key ABSENT means) is `design/sim_ngspice.py` — the v2.07 `design/sim.py`
  under a new name, behaviour untouched. `bridge` is `design/sim_bridge.py`. `design/sim.py` now implements
  nothing: it reads the key and replaces itself in `sys.modules` with the module it names, so
  `from design import sim` hands back the lane itself and `sim.run` / `sim.DECK_VARS` are the
  lane's own objects — a star-import would have copied the lane's policy constants into a second
  namespace, and every later assignment to one would have changed the copy.
- **`design/sim_bridge.py`** — the wrapper the copies had in common, over the platform's
  bridge-lane package: `work()` (the platform's own `work_root` — never the repo, never `/tmp`,
  never a tool-named path), `simulator()`, `MODE`, `run()` (deck text, `extra_files`,
  `include_files`, mode args), `preflight()` and a `main()` that separates "no bridge profile on
  this machine" (exit 2, not a stop) from "the lane ran and failed" (exit 1). It carries no driver:
  upload, run, download, result parsing, redaction and the busy marker are the platform's, and a
  test asserts this module never opens a connection itself.
- **`design/pdk.py` is template code now**, with four things to fill in — `REVISION`, `SECTIONS`,
  and the two variable names. `TOKEN` / `restore()` / `section()` / `models_block()` and the
  hardened `library()` are shipped. The pin binds on EVERY route, as `resolve()`'s `DECK_VAR_PINS`
  does on the open lane, with the same typed escape hatch (`<NAME>_ALLOW_MISMATCH=1`) and the same
  rule that no message ever echoes the value. Deck SYNTAX stays out of it: the preamble is
  `design/dut.py`'s, and `pdk.models_block()` supplies only the `include` lines.
- **The kit path comes from the environment; nothing is scanned for.** Three variables, in order:
  `<DESIGNTAG>_PDK_LIB` (scoped to the design — what a person exports), `<PREFIX>_PDK_LIB` (the
  name the frozen decks carry, so it cannot be renamed without re-freezing every reference), and
  the per-MACHINE `<PDK-ID>_PDK_LIB` **derived from `pdk:` in `harness.yaml`** (`ihp-sg13g2` →
  `IHP_SG13G2_PDK_LIB`), which belongs in the account's env file and serves every design in that
  process. The route that recovered the path by grepping a NEIGHBOURING clone's committed deck is
  deliberately NOT shipped: it depended on which repos a person had cloned, it resolved relative to
  the checkout so it broke inside a git worktree — the layout `CLAUDE.md` tells every agent to work
  in — and it made the library behind a certified number depend on an unrecorded local layout.
- **The doctor reports an unresolved process without simulating.** The probe is one resistor and
  would pass without the kit, but a lane that cannot bind this design to its model library is not
  alive — the rule the open lane already applies to an unset `DECK_VARS`. Unfilled template
  placeholders are reported the same way.
- `python -m design.sim` (`make doctor`) dispatches to the selected lane's `main()`; both lanes
  grew one.
- A comment in the open lane's `DECK_VAR_PINS` used a real commercial kit's revision name as its
  example. This repo is public: it is a placeholder now.

**Prerequisite for `lane:`, and only for it.** The key needs a platform whose
`spicexplorer_harness.config.Harness` carries a `lane: str = ""` field (beside `sim_env` /
`work_env`); an older platform refuses the key outright — `harness.yaml: unknown keys ['lane']` —
rather than ignoring it, which is the right failure but a confusing one if unexpected. Run
`make shared-update` on the shared root before a design writes the key. **Nothing else in this
release needs it:** the rename, `sim_bridge.py`, `pdk.py`, the doctor and the docs all work on
today's platform, and a design that never writes `lane:` never reads the field.

**Taking it:** `make template-update`, then one decision and one manual step. Rehearsed on a copy
of a v2.07 design that had edited its `sim.py`, so this is what the run actually does:

1. **`<package>/sim.py` comes back CONFLICTED, and that is the whole migration.** The update
   applies file by file, so the rename is not seen as one: `sim_ngspice.py`, `sim_bridge.py` and
   `pdk.py` are ADDED clean, and `sim.py` — a whole-file rewrite into the dispatcher — meets
   whatever the design put in it. Nothing is lost: the design's lines sit under `<<<<<<< ours`.
   Resolve it by taking **theirs** for `sim.py` (the dispatcher holds no policy) and moving the
   `ours` lines — `DECK_VARS`, `DECK_VAR_SCOPE`, `DECK_VAR_PINS`, `SPICEINIT_EXTRA`, any custom
   `preflight` probe — into the newly added `<package>/sim_ngspice.py`, which is where they now
   live. Then `make lint && make test && make doctor`, and record the release yourself
   (`echo 2.08 > .sx/template-version`): a conflicted run deliberately does not.
2. `harness.yaml` is never propagated (it is this design's), so add `lane:` yourself if you want
   the bridge lane, and `pdk:` if you want the per-machine variable derived.

A commercial-PDK design already carrying its own hand-ported lane: take this release, then DELETE
its local `sim.py`/`pdk.py` mechanism and keep only what is genuinely its own — `REVISION`,
`SECTIONS`, the two variable names, `MODE`, and any probe helpers. Export the per-machine variable
once instead of relying on a neighbouring clone.

## v2.07 — the lifecycle is the harness's, not a copy in every design

Minor, and the largest single change to `design/metrics.py` since v1: **321 lines become 151.**

`promote`, `evaluate`, `frozen_dir`, `frozen_decks`, `certified_card`, `certify`, `drift_limit`,
`drift`, `table` and `main` now come from `spicexplorer_harness.lifecycle.Lifecycle`. They had
byte-identical ASTs in four design repos, and the argument for extracting them is not the 183
lines: **this** is the block that spread AT-01 — a bench that never ran certifying as passing — so
fixing it meant four commits on four branches with four reviews (platform #176). What stays here
is what a lifecycle cannot know: the reference point, how a design becomes deck files, how decks
become scored values (`run_decks`), how a `design.json` loads, and `KEYMAP`.

Every name is re-exported, so `layout/signoff.py`, an experiment or a doc that calls
`metrics.promote` / `metrics.evaluate` / `metrics.certify` keeps working. **Four behaviours
differ**, and a design adopting this must know them:

- **`certify()` returns a `CertifyResult`**, not a dict. `result.doc` is the old dict;
  `result.scorecard`, `result.violations`, `result.decks`, `result.written` are the parts.
- **`drift()` returns `Drift` records**, not `(key, got, certified, why)` tuples. `d.key`, `d.got`,
  `d.certified`, `d.why`, `d.missing`, `d.line()`.
- **The provenance block is always written**, backed by an `evidence: awaiting` ledger row, and
  signing adds a second `evidence: signed` row. The copies wrote the block only when signed, which
  is how the LDO instantiation ended up with a `scorecard-recompute` no signature could green.
- **The scorecard keeps INTEGER metrics.** The copies filtered on `isinstance(v, float)`, so a
  spec'd integer never reached the card while `violations()` still judged the design on it
  (HAR-03). The certified card of a design with an integer spec key will therefore GAIN a column;
  re-certify deliberately.

`run_decks` now accepts a deck key that is either the bench name or the deck's file name
(`op` or `op.spice`) — the lifecycle hands over file names, because those are the bytes it freezes.

**Taking it:** `make template-update`. A design that edited `design/metrics.py` — most will have,
at least in `KEYMAP` — gets a three-way merge there; keep your `KEYMAP`, `measure()` and
`run_decks`, and take the `Lifecycle` wiring at the bottom. A design whose tests patch
`metrics.run_decks`, `metrics.certified_card` or `metrics.frozen_dir` must patch the lifecycle's
own inputs instead (`dataclasses.replace(metrics.L, score=…)`): the shared implementation holds
its inputs and never reads those module attributes. **This needs a platform new enough to carry
`spicexplorer_harness.lifecycle`** — platform `8dfa0f2` or later; run `make shared-update` on the
shared root before a design takes this release.

## v2.06 — a deck variable is checked, and scoped to the design

Minor. One defect, reproduced in three designs before it was fixed
(MacAnalog/macanalog-design-directory#38).

- **A deck variable could point anywhere** (`design/sim.py`). `resolve()` substituted whatever the
  environment held. The designs that carry a model-library revision therefore checked it in their
  own `pdk.library()`, and two of the three put the check on the *derived fallback* — the route
  nobody uses — so one wrong export produced a full green `make check` against a different process
  revision, recorded nowhere but the shell that ran it. `DECK_VAR_PINS` (name -> the substring the
  value must carry, usually the revision `doc/environment.md` pins) is now enforced by `resolve()`,
  i.e. on the one route every deck takes. `<NAME>_ALLOW_MISMATCH=1` keeps a deliberate
  cross-revision run possible and makes it visible: it has to be typed.
- **The variable was shared by construction** (`design/sim.py`). The bare name is the text inside
  every frozen deck, so two designs can read one export — and a name taken from the env prefix is
  not unique either (two designs in this lab share `OTA_`). `DECK_VAR_SCOPE` adds a design-scoped
  name, read FIRST, without renaming what the frozen decks carry; `deck_var_names()` is the one
  place the order is defined, and `preflight()` reports against the same candidates.
- Neither message echoes the value: they name the variable and the pin. A machine-specific path
  stays out of logs.

**Taking it:** both knobs default to empty, so a design that declared only `DECK_VARS` is
unaffected. To adopt, set `DECK_VAR_SCOPE = "<short design tag>"` and
`DECK_VAR_PINS = {"<NAME>": "<revision>"}` in `design/sim.py`. A design that hand-edited `resolve()`
will get a three-way conflict there from `make template-update`; the merged result should keep the
candidate loop and the pin check.

## v2.05 — four ways the harness reported work it had not done

Minor. Every one of these was reproduced before it was fixed (codex review 2026-09-10, items
AT-01…AT-04); each carries a test that fails on the old code.

- **A bench whose `.meas` failed was recorded `ok`** (`design/metrics.py`). The deck simulated, the
  measure did not, `promote` made the column NaN, `certify()` keeps only non-NaN floats — so the
  metric left the card, and `drift()` iterates the CERTIFIED keys, so it could never be missed
  again. A `make certify && make freeze` sha-locked a reference one spec column short. There are
  three bench statuses now: `ok`, `meas_error` (it ran; a measure did not) and `sim_error` (it did
  not run). Only `ok` certifies; a partial bench still contributes the numbers it produced.
- **`spec-quotes` matched the whole document** (`scripts/lint.py`). Every numeric token in
  `doc/target-spec.md` went into one set, so a baseline column holding the wrong value passed
  whenever the certified number appeared anywhere else in the file. Matched per row now, against
  the line that names the row (its `id:`, the `S3` at the front of its label, its key or its
  label); a row no line names is a failure of its own.
- **`template-update` recorded a release that did not land** (`scripts/template_update.py`).
  `.sx/template-version` was written before the CONFLICT scan, so a conflicted update still
  advanced the version and the next update never offered the rejected change again. Written only
  on a clean apply. A file the release ADDS whose apply failed is REJECTED, not "skipped".
- **`template-migrate --dry-run` wrote to the repository** (`scripts/migrate_v1_to_v2.py`). It
  added the `template` remote and ran `git fetch --tags --force` — which can move a tag the design
  already had — before it looked at the flag. A dry run now answers read-only and says so.

**Taking it:** `make template-update`. `metrics.py` is the file a design is most likely to have
edited, so expect the merge to want a decision there; the change is the three-status `one()` and
the `!= "sim_error"` promotion condition.

## v2.04 — the sign-off tree's `figs/` and `tables/` actually survive

Minor. The migration created them with `mkdir` and git does not track an empty directory, so a
migrated design ended up with a `signoff/` tree that its own `README.md` describes and the repo
does not have — no `figs/`, no `tables/`, at any fidelity. Measured on two designs.

They are now created with a `.gitkeep`, the same way the template ships them.

**Why this one is worth a release rather than a shrug:** those two directories are where the
evidence for a claim goes. A structure that documents a home which does not exist teaches the next
agent that the home is optional.

## v2.03 — say what the relocation does to the ledger

Minor. 2.02 moved a frozen directory and repointed its scorecard. The **ledger** records the same
paths, and it is deliberately not rewritten — *"never hand-edit the ledger: an edited row is not
evidence of a run"*. A row naming the old path is a true record of where the file was when that run
happened.

The consequence is a `scorecard-recompute` failure for those rows **in the checkout that holds
them**. `runs/` is git-ignored and per checkout, so a fresh clone never sees it, and it clears at
the next certification. That is now said in the migration's own output rather than discovered
afterwards — a lint going red for a reason nobody can act on is the failure mode the harness
already avoids for fresh clones.

## v2.02 — a frozen directory CAN move; it just has to take its pointers with it

Minor. This corrects an over-strong rule in 2.00/2.01, which refused to move any frozen directory
on the strength of one design's breakage.

**What was actually true.** A scorecard's `provenance` block records `script` and `raw` as
repo-relative paths, each beside a sha of that file's **contents**. Move the directory and a path
pointing inside it stops resolving — `scorecard-recompute` reports *"raw `<path>` is missing"*.

**What was not true: that this makes the move impossible.** Rewriting the pointer keeps every hash
valid, because no byte of the rawfile, the scorer, or any number changes. The move is a relocation
record, not a re-measurement. And it does not apply at all to a scorecard with no `provenance`
block — one design in the fleet has six frozen dirs and no provenance paths, and would never have
been affected.

**So `move_reference` now relocates.** It reads each scorecard, moves the directory, repoints only
the provenance keys that pointed inside it, and updates `harness.yaml`. Run `make freeze`
afterwards: `SHA256SUMS` covers `scorecard.json`.

**Two things are still never inferred**, and both are arguments or refusals rather than guesses:

- **Which frozen dir is the design of record** — `--design-of-record <dir>`. `reference_scorecard`
  cannot answer it: that key means *the scorecard `make check` reproduces*, which a design may
  legitimately point at a prior-art yardstick it is trying to beat.
- **Whether a dir is a result at all.** A yardstick, a control and a withdrawn row are frozen too,
  and they stay in `decks/`. `signoff/` is for this design's own results.

**The lesson:** one design's failure is evidence about that design. Generalising it into a rule for
every design cost two repos the structure they were entitled to.

## v2.01 — three defects the first real migrations found

Minor: propagatable into any design already on 2.00. All three were found by running the migration
against live designs, and every one of them failed silently or confusingly rather than loudly.

| defect | what happened | fix |
|---|---|---|
| `frozen:` read with a single-line regex | a design whose list wraps over two lines was told **"nothing is frozen yet"** — with six frozen directories — and advised to certify into a fresh path | `re.S`, and the comment says why a false negative here is worse than no check |
| `artifact_home` used a module-level `subprocess` | the check crashed (`NameError`) on any design whose own `lint.py` does not import it | imports it locally, so it never depends on a design's import block |
| a missing `scripts/template_update.py` | raw `ModuleNotFoundError` traceback mid-run | a refusal that says whether the repo is template-derived and how to restore the file |

**The lesson worth keeping:** two of these produced confident wrong output rather than an error. A
migration that reports is only useful if what it reports is true, so test it against the messiest
real repo you have, not against the template.

## v2.00 — every artefact has a home (MAJOR: directories move)

**Why this is a MAJOR.** A three-way merge can change a file's contents; it cannot move a file.
2.00 renames one directory and adds another, so it crosses by script, not by merge:
`scripts/migrate_v1_to_v2.py` (`make template-migrate ARGS="--dry-run"` first). It moves things,
repoints `harness.yaml`, writes the new version, and commits nothing.

### What changed

| change | before | after |
|---|---|---|
| reference material is named for what it is, not its file format | `pdf/` | `references/` (`papers_dir`, `papers_index`) |
| the design of record has one tree, organized by simulation fidelity | `decks/reference/`, renders loose in `layout/` | `signoff/` — `schematic/`, `layout/`, and one directory per fidelity (`prelayout`, `postlayout-pex`, `postlayout-em`), each with `decks/`, `scorecard.json`, `figs/`, `tables/`, `REPORT.md` |
| an experiment says which phase of the design it belongs to | — | `**Phase:**` in its README, `Phase` first in `experiments_rows` |
| an experiment's numbers get a committed, diffable form | `figs/` only | `figs/` + `tables/`, written by the new `exp.csv` |
| the package stops carrying link-specific shims | `<pkg>/stimulus.py`, `<pkg>/eye.py` | import `spicexplorer_waveview.stimulus` / `.eye` directly. **Nothing is deleted from an existing design** |

### What it enforces

Two new checks in `scripts/lint.py`, both with their fix in the message:

- **`artifact-home`** — a committed `.png`, `.svg`, `.pdf`, `.csv` or `.gds` must sit in a home the
  repo has declared: `experiments/` (wide open — that is the working space), `signoff/`, `layout/`,
  `decks/`, `doc/`, `references/`, `notebooks/`. Raw simulator output is never committed at all; it stays in
  the scratch root. The reason is not tidiness: a reviewer who cannot find the evidence treats the
  claim as unsupported.
  **The escape hatch is a declaration, not an exemption.** A design with its own durable output
  directory — a physics lane, a report tree, an imported legacy set — adds one line to
  `ARTIFACT_HOMES` in its own `scripts/lint.py` saying what lives there. Measured across the
  owner's six designs, that is one or two lines each. The migration prints the count and the
  directories before you decide.
- **`signoff-index`** — every directory under `signoff/` appears in `signoff/README.md`, with what
  the number includes, its scorecard, its status and who signed it. An undescribed directory in the
  trusted tree looks certified and says nothing.

### Migration

**It applies only to a repo the harness describes.** Two of the lab's designs predate the template
and carry no `harness.yaml`; the script refuses them by name rather than moving their directories
and failing partway. A repo outside the harness contract stays outside it until it adopts the
template deliberately.

**Prerequisite: the design must already be at 1.04 or later** (`make template-update` first). 1.04
is where the file-by-file three-way apply this migration reuses was added; crossing from earlier
in one step would apply the whole patch atomically, and one missing file would silently roll back
every file that had merged. The script checks and refuses before it moves anything.

The script ships in 2.00, so a design still on 1.xx has to fetch it before it can run it. Two
lines, from the design's repo root:

```bash
git fetch --tags --force https://github.com/MacAnalog/agentic_design_template.git
git show v2.00:scripts/migrate_v1_to_v2.py > scripts/migrate_v1_to_v2.py && chmod +x scripts/migrate_v1_to_v2.py
```

Then, on a clean worktree (the script refuses a dirty one, so `git status` afterwards shows
exactly what it did):

```bash
python3 scripts/migrate_v1_to_v2.py --dry-run   # read the plan; nothing moves
python3 scripts/migrate_v1_to_v2.py             # apply it; nothing is committed
make lint && make test && make check            # the reference MOVED — prove it still reproduces
```

It does two things in order: takes 2.00's ordinary content changes by three-way merge, file by
file (the same machinery `make template-update` uses), then makes the moves a merge cannot make.
Conflicts are reported per file and are decisions, not failures — `scripts/lint.py` is the usual
one, where 2.00's two new checks meet the design's own.

Then fill each experiment's `**Phase:**` and the table in `signoff/README.md`, read `git status`,
and commit. The script refuses to run on a dirty worktree, so `git status` afterwards shows
exactly what it did.

**It never moves a frozen directory, and that is deliberate.** An earlier draft moved a single
unambiguous `decks/<ref>` into `signoff/prelayout/decks`. Trialled on a live design, that FAILS: a
certified `scorecard.json` names its own artefacts by path in its provenance block, so the move
invalidates the certification (`scorecard-recompute`: *"raw `decks/candidate/decks.sha256` is
missing"*). Regenerating it needs a live re-certification and a second actor's signature — a
deliberate act, never a side effect of a rename. The script now reports where the design of record
should end up and leaves the bytes alone; you point `signoff/` at it, and it moves for free the
next time you re-certify.

**Nor does it pick WHICH directory is the design of record** when several are frozen — and it
warns you not to let `reference_scorecard` pick either. That key means *the scorecard `make check`
reproduces*, which a design may legitimately point at a prior-art yardstick it is trying to beat.
Measured on a live design: the directory named `reference` was the yardstick and the one named
`candidate` was the design of record, so following the key would have promoted prior art into the
sign-off tree and left the real design behind.

## v1.05 — every document rewritten against the writing standard

MINOR, and it touches only prose. The lab's `design-writing` skill now says how any document in a
design repo is written, revised and audited: the field's own terminology and no coined labels, no
adjective without a number, what must be a table or a plot rather than a sentence, paragraphs a
designer can scan with the agent-grade detail layered underneath, and a contract per document type.

Every `.md` in this template was audited against it and rewritten, and each rewrite was checked by a
second pass for lost facts, false additions, broken structure and style regressions. Nothing that
any document asserts changed; the numbers, paths, commands, placeholders and tables are the same.
The word *reduction* is now defined where each document first uses it, which was the defect that
prompted the rule about coined nouns.

## v1.04 — apply file by file, and say what each file did

MINOR. `git apply` is atomic. On the first real propagation, one file the design had never carried —
a test module it dropped — aborted the whole patch and rolled back every file that had already
merged, without reporting it. `make template-update` now applies each file on its own and prints one
line per file: `added`, `merged`, `skipped` (the design does not carry the file the change edits) or
`CONFLICT`. A design receives every file that can land, and the report names the ones that did not.

## v1.03 — the package's generic modules propagate too

MINOR. `1.02` held back `metrics.py` and `bench.py` alongside `dut.py`, so a design could not
receive the scorecard-lifecycle and reduction work those files carry — the work `1.01` added.
Inside the package, only `dut.py` is design-owned now: the template's is a stub, so propagating its
changes into a real topology yields conflicts and nothing a design can use. Everything else merges
three-way. A conflict inside `metrics.py`, usually at `KEYMAP`, is a decision for the designer, not
a failure of the update.

## v1.02 — template versioning

MINOR. A design can now tell which template release it came from and take later minor work.

- `.sx/template-version` (`#.##`), inherited by every repo created from this template.
- `make template-status` / `make template-update` (`scripts/template_update.py`): fetch the
  template as a remote, diff the recorded release against the target, apply with a three-way merge,
  and stop with conflict markers wherever the design's own edits meet the template's. Nothing is
  committed and nothing is overwritten silently.
- The design owns `harness.yaml`, its `doc/`, `pyproject.toml`, `experiments/`, `decks/`, `layout/`
  and, inside its package, `dut.py`, `bench.py` and `metrics.py`; everything else propagates.
- `template_update.py` handles the instantiation rename: it re-roots the package half of the diff
  from `design/` onto whatever `harness.yaml` names. A hunk whose *text* names the template's
  `design.` package still arrives spelled that way, so run `make lint && make test` after an update
  and fix what they report.

## v1.01 — certifiable reductions, portable decks

MINOR. Both halves come from certifying a real design (issue #13).

- `design/bench.py`: the code that turns a bench's simulated waveform into the number the spec is
  written in — the bench's **reduction** (`PRODUCES` + `reduce()`) — shared by the harness and the
  experiments share. A bench whose answer is post-processing — phase margin, crossover, settling
  time — is certifiable only when the reduction lives here rather than in an experiment's `run.py`.
  `metrics.KEYMAP` is built from `PRODUCES`, and `metrics.run_decks` merges the reduction into each
  bench record before anything is promoted, logged or frozen.
- `design/sim.py`: `DECK_VARS` + `resolve()`. The deck names a machine-specific path `$VAR` and
  `run()` substitutes it, so what is built, logged, frozen and diffed stays portable. `make doctor`
  fails when a declared variable is unset.
- `scripts/lint.py`: `deck_portable` refuses an absolute include path in a frozen deck.
- CLAUDE.md rules 1 and 2, `doc/benches.md` and `doc/environment.md` state both rules.

## v1.00 — first tagged release

The template as it stood on 2026-09-09: the harness lifecycle (`certify` / `freeze` / `baseline` /
`check`), the ngspice lane wrapper, the ledger and context pack, the `deck_rebuild` and
`spec_quotes` lints, the linked agents and skills, the layout and sign-off stubs, and the docs
skeleton. A design cut before this tag can record `1.00` and update from there; its first update
may raise conflicts a human resolves rather than overwrite what the design changed.
