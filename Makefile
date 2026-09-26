# The front door.  `make help` lists everything.  The generic harness (lint, pack,
# runs, freeze) is the platform's spicexplorer-harness driven by harness.yaml;
# design/ and scripts/ hold only what is specific to this design.

# Prefer the checkout's own venv (uv sync creates it); fall back to python3.
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
HARNESS := $(PY) -m spicexplorer_harness.cli --repo .
ARGS ?=
# `make clean-runs AGE=48`: how long a run's simulator log must have been cold
# before the sweep may remove that run dir (hours).
AGE ?= 24

help:  ## list every target
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

# One-time per checkout. SX_ROOT = the SpiceXplorer workspace checkout (the lab exports it in
# ~/.sx_env; a read-only shared checkout is fine — editable installs write only into ./.venv).
init:  ## set up this checkout: .sx/platform -> $$SX_ROOT/spicexplorer-platform, the .sx/skills library + agent/skill links, uv sync
	@test -n "$(SX_ROOT)" || { echo "SX_ROOT is not set: export SX_ROOT=<your spicexplorer-workspace checkout> (the lab puts it in ~/.sx_env)"; exit 2; }
	@test -f "$(SX_ROOT)/spicexplorer-platform/packages/spicexplorer-harness/pyproject.toml" || { echo "SX_ROOT=$(SX_ROOT) holds no spicexplorer-platform/ checkout: run 'make setup' there, or fix SX_ROOT"; exit 2; }
	@mkdir -p .sx && ln -sfn "$(SX_ROOT)/spicexplorer-platform" .sx/platform
	@git submodule update --init --recursive .sx/skills
	@.sx/skills/bin/sx-link . --set design
	@uv sync
	@echo "init OK: .sx/platform -> $$(readlink .sx/platform); $$(ls .claude/agents | wc -l) agents + $$(ls .claude/skills | wc -l) skills linked from .sx/skills; next: make doctor"

template-status:  ## which template version this design was cut from (.sx/template-version) and what minor updates exist since
	@$(PY) scripts/template_update.py status

template-update:  ## propagate the template's MINOR updates into this design (three-way merge; nothing committed). VER=1.03 to pick one
	@$(PY) scripts/template_update.py update $(VER)

template-migrate:  ## cross a MAJOR template release (1.xx -> 2.00): moves directories, repoints harness.yaml, commits nothing. ARGS="--dry-run" first
	@$(PY) scripts/migrate_v1_to_v2.py $(ARGS)

# Before `make init`, .sx/skills is an empty directory with no .git, so `git -C .sx/skills` finds
# the design's own repository one level up: the fetch and checkout below then moved the design's
# HEAD to a detached origin/main. A submodule's .git is a file, so the check is -e, not -d.
skills-update:  ## move .sx/skills (the shared agent/skill library) to its main, re-link, and stage the pin — then commit it
	@test -e .sx/skills/.git || { echo "REFUSING: .sx/skills is not initialised (it has no .git), so its git commands would run in this design's own repository: run 'make init' first"; exit 2; }
	@git -C .sx/skills fetch -q origin main && git -C .sx/skills checkout -q origin/main
	@.sx/skills/bin/sx-link . --set design
	@git add .sx/skills .claude
	@echo "skills @ $$(git -C .sx/skills rev-parse --short HEAD): $$(ls .claude/agents | wc -l) agents + $$(ls .claude/skills | wc -l) skills linked; staged — commit the pin: git commit -m 'skills: bump .sx/skills to $$(git -C .sx/skills rev-parse --short HEAD)'"

lint:  ## repo invariants (harness.yaml + scripts/lint.py extras); failures carry their remediation
	@$(PY) scripts/lint.py

check:  ## lint + the reference reproduces its certified scorecard
	@rc=0; $(PY) scripts/lint.py || rc=1; echo; $(PY) -m design.metrics --check || rc=$$?; exit $$rc
	# `|| rc=$$?` (not `|| rc=1`): since platform #217 a gate that COULD NOT RUN exits 3, a drift 1 —
	# folding every nonzero to 1 would make an uncertified design indistinguishable from a drifted one

baseline:  ## simulate the frozen reference decks and print the scorecard (no drift verdict)
	@$(PY) -m design.metrics --baseline $(ARGS)

certify:  ## (re)certify the reference into the frozen dir, then `make freeze` deliberately
	@$(PY) -m design.metrics --certify $(ARGS)

pack:  ## working-memory context pack (K="noise gain" S="symptom text")
	@$(HARNESS) pack $(K) $(if $(S),--symptom "$(S)") $(ARGS)

runs:  ## query the run ledger (ARGS="--fails" | "--best gain_db --desc" | "--exp 001" | "--where topology=b")
	@$(HARNESS) runs $(ARGS)

freeze:  ## write SHA256SUMS into the frozen dirs after a deliberate certification
	@$(HARNESS) freeze

# The scratch report runs WHATEVER the probe said, and the PROBE's exit code is what `make doctor`
# returns: a down lane is exactly when nobody looks at the disk, and 212 GB of already-reduced
# records is how a shared machine fills up (template#37).
doctor:  ## is the lane alive? (a one-resistor deck through design.sim) + this checkout's scratch usage
	@rc=0; $(PY) -m design.sim || rc=$$?; $(PY) scripts/clean_runs.py --report; exit $$rc

test:  ## the generic design modules (lane, batches, plots, scorecard); live tests skip without ngspice
	@OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 $(PY) -m pytest -q

# The gate, attached to something. `make lint && make test && git commit && git push` READS as
# conditional, and twice it was not: the lint ran as a separate earlier command, watched failing,
# and the chain committed and pushed red anyway (#31). `make guard` is one command that cannot be
# half-typed; `make hook-install` is the version that cannot be forgotten.
# Clause order is deliberate: the tree comes FIRST because lint and test judge the WORKING TREE,
# not the commit being pushed — their verdict means nothing while edits are still loose — and
# `--cached` is checked separately because `git diff --quiet` alone passes on staged-but-
# uncommitted changes, which is exactly the window this guards.
guard:  ## refuse unless the tree is clean and lint + tests are green (GUARD_SKIP_TEST=1 drops the test clause)
	@git rev-parse --git-dir >/dev/null 2>&1 || { echo "REFUSING: not a git checkout, so there is no tree to judge"; exit 1; }
	@git diff --quiet || { echo "REFUSING: unstaged changes in the tree (git status; commit or stash them)"; exit 1; }
	@git diff --cached --quiet || { echo "REFUSING: staged but uncommitted changes (git status; commit them)"; exit 1; }
	@$(MAKE) --no-print-directory lint || { echo "REFUSING: make lint is red"; exit 1; }
	@if [ -n "$(GUARD_SKIP_TEST)" ]; then \
	   echo "guard: GUARD_SKIP_TEST=$(GUARD_SKIP_TEST) — the test clause was SKIPPED deliberately"; \
	 else \
	   $(MAKE) --no-print-directory test || { echo "REFUSING: make test is red"; exit 1; }; \
	 fi
	@echo "guard: tree clean, lint green, tests $(if $(GUARD_SKIP_TEST),SKIPPED,green)"

hook-install:  ## opt-in, per clone: install the pre-push hook that runs `make guard` (honours core.hooksPath; linked worktrees share it)
	@$(PY) scripts/githook.py install

hook-remove:  ## remove the pre-push guard hook (a hook this repo did not write is left alone)
	@$(PY) scripts/githook.py remove

notebooks:  ## execute notebooks/*.ipynb in place (outputs committed, so a reader sees the numbers)
	@for nb in notebooks/*.ipynb; do [ -e "$$nb" ] || continue; \
	  PATH="$(CURDIR)/.venv/bin:$$PATH" $(PY) -m jupyter nbconvert --to notebook --execute \
	  --inplace --ExecutePreprocessor.timeout=1800 $$nb || exit 1; done

clean:  ## delete this checkout's work dir + experiment output (never the ledger)
	@d=$$($(PY) -c "from design.sim import work; print(work())" 2>/dev/null); \
	  [ -n "$$d" ] && echo "rm -rf $$d" && rm -rf "$$d"; rm -rf experiments/*/out/

# The mid-campaign sweep `make clean` cannot be: it never touches a run another process is
# writing, one nothing has reduced, or one whose log is still warm — and it says why it kept each
# of them. `make clean` stays for "this checkout is finished with".
clean-runs:  ## delete run dirs whose reduction is in the ledger and whose log is older than AGE hours (AGE=24; ARGS="--dry-run")
	@$(PY) scripts/clean_runs.py --age $(AGE) $(ARGS)

.PHONY: help init template-status template-update template-migrate skills-update lint check baseline certify pack runs freeze doctor test guard hook-install hook-remove notebooks clean clean-runs
