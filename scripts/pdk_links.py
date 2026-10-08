#!/usr/bin/env python3
"""`make init` / `make skills-update`: link the library's `pdk-<id>` set when `harness.yaml` declares `pdk:`.

The skill library ships one link set per process it has a knowledge base for
(`.sx/skills/linksets/pdk-<id>.txt`, for example `pdk-ihp-sg13g2`). It is applied on top of the
`design` set, and only for the process this design declares in `harness.yaml`, never for the
registry entry or the repo name. Three cases:

- `pdk:` is absent or empty: nothing is linked and nothing is printed.
- `pdk: <id>` and the pinned library has `linksets/pdk-<id>.txt`: `sx-link . --set pdk-<id>`.
- `pdk: <id>` and the pinned library has no such set: one INFO line, exit 0.

Standard library only: `make init` runs this before `uv sync` has made the venv, so PyYAML may not
be importable. `declared_pdk` reads the one top-level `pdk:` line; a test checks that it agrees
with the harness's own loader on this repo's `harness.yaml`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# A top-level `pdk:` line (no indentation, so a nested key of the same name does not count).
_PDK_LINE = re.compile(r"^pdk:[ \t]*(.*?)[ \t]*$", re.MULTILINE)
# What an id may be spelled with; anything else is not used to build a file name.
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def declared_pdk(harness_text: str) -> str:
    """The value of the top-level `pdk:` key, or "" when it is absent, empty or null."""
    m = _PDK_LINE.search(harness_text)
    if not m:
        return ""
    value = m.group(1)
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        return value[1:end] if end > 0 else ""
    value = re.split(r"[ \t]#", value, maxsplit=1)[0].strip()
    return "" if value in ("", "~", "null", "Null", "NULL") or value.startswith("#") else value


def linkset(root: Path, pdk: str) -> str | None:
    """`pdk-<pdk>` when the library at `<root>/.sx/skills` ships that link set, else None."""
    if not pdk or not _ID.match(pdk):
        return None
    name = f"pdk-{pdk}"
    return name if (root / ".sx" / "skills" / "linksets" / f"{name}.txt").is_file() else None


def main(root: Path = REPO) -> int:
    try:
        text = (root / "harness.yaml").read_text()
    except OSError:
        return 0
    pdk = declared_pdk(text)
    if not pdk:
        return 0
    name = linkset(root, pdk)
    if name is None:
        print(
            f"INFO: harness.yaml declares pdk: {pdk}; the library at .sx/skills has no "
            f"linksets/pdk-{pdk}.txt, so no per-PDK skill is linked"
        )
        return 0
    return subprocess.run(
        [str(root / ".sx" / "skills" / "bin" / "sx-link"), str(root), "--set", name], check=False
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
