"""pytest scratch lives under $SX_SCRATCH (never /tmp): the lane rejects /tmp work roots."""

from __future__ import annotations

import os
from pathlib import Path


def pytest_configure(config):
    if not config.option.basetemp:
        root = Path(os.environ.get("SX_SCRATCH") or Path.home() / "sx-scratch")
        base = root / "pytest" / Path(__file__).resolve().parents[1].name
        base.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(base)
