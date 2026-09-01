# Thin wrapper over the platform's `spicexplorer-harness` CLI. The design logic lives in lab/.
PLATFORM ?= ../../spicexplorer-platform
PY := uv run --project $(PLATFORM)
HARNESS := $(PY) spicexplorer-harness --repo .

.PHONY: help lint check pack runs freeze clean

help:
	@echo "lint     repo invariants (failures carry their remediation)"
	@echo "check    lint + the reference reproduces its certified scorecard"
	@echo "pack     working memory: make pack K=\"noise irn\" S=\"symptom text\""
	@echo "runs     query the ledger: make runs ARGS=\"--fails\""
	@echo "freeze   write SHA256SUMS into the frozen dirs"

lint:
	$(HARNESS) lint

check: lint
	$(PY) python -m lab.metrics --check

pack:
	$(HARNESS) pack $(K) $(if $(S),--symptom "$(S)")

runs:
	$(HARNESS) runs $(ARGS)

freeze:
	$(HARNESS) freeze

clean:
	rm -rf runs/ experiments/*/out/
