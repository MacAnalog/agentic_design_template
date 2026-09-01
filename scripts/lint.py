#!/usr/bin/env python3
"""`make lint` runs the generic checks; add this repo's own `def check(L: Lint)` to EXTRA."""

import sys
from pathlib import Path

from spicexplorer_harness import lint, load

EXTRA = ()  # e.g. (reference_rebuilds,) — a check that the frozen deck still rebuilds from lab/

sys.exit(lint.main(load(Path(__file__).resolve().parents[1]), extra=EXTRA))
