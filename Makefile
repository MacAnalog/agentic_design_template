# The front door.  `make help` lists everything.  The generic harness (lint, pack,
# runs, freeze) is the platform's spicexplorer-harness driven by harness.yaml;
# design/ and scripts/ hold only what is specific to this design.

# Prefer the checkout's own venv (uv sync creates it); fall back to python3.
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
HARNESS := $(PY) -m spicexplorer_harness.cli --repo .
ARGS ?=

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

skills-update:  ## move .sx/skills (the shared agent/skill library) to its main, re-link, and stage the pin — then commit it
	@git -C .sx/skills fetch -q origin main && git -C .sx/skills checkout -q origin/main
	@.sx/skills/bin/sx-link . --set design
	@git add .sx/skills .claude
	@echo "skills @ $$(git -C .sx/skills rev-parse --short HEAD): $$(ls .claude/agents | wc -l) agents + $$(ls .claude/skills | wc -l) skills linked; staged — commit the pin: git commit -m 'skills: bump .sx/skills to $$(git -C .sx/skills rev-parse --short HEAD)'"

lint:  ## repo invariants (harness.yaml + scripts/lint.py extras); failures carry their remediation
	@$(PY) scripts/lint.py

check:  ## lint + the reference reproduces its certified scorecard
	@rc=0; $(PY) scripts/lint.py || rc=1; echo; $(PY) -m design.metrics --check || rc=1; exit $$rc

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

doctor:  ## is the simulation lane alive? (a one-resistor deck through design.sim, per-run .spiceinit proven)
	@$(PY) -m design.sim

test:  ## the generic design modules (lane, batches, plots, scorecard); live tests skip without ngspice
	@OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 $(PY) -m pytest -q

notebooks:  ## execute notebooks/*.ipynb in place (outputs committed, so a reader sees the numbers)
	@for nb in notebooks/*.ipynb; do [ -e "$$nb" ] || continue; \
	  PATH="$(CURDIR)/.venv/bin:$$PATH" $(PY) -m jupyter nbconvert --to notebook --execute \
	  --inplace --ExecutePreprocessor.timeout=1800 $$nb || exit 1; done

clean:  ## delete this checkout's work dir + experiment output (never the ledger)
	@d=$$($(PY) -c "from design.sim import work; print(work())" 2>/dev/null); \
	  [ -n "$$d" ] && echo "rm -rf $$d" && rm -rf "$$d"; rm -rf experiments/*/out/

.PHONY: help init template-status template-update template-migrate skills-update lint check baseline certify pack runs freeze doctor test notebooks clean
