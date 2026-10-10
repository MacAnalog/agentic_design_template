#!/usr/bin/env python3
"""`make init` / `make skills-update`: link the per-PDK skills for the `pdk:` `harness.yaml` declares.

Two sources, applied after the library's `design` set and only for the process this design
declares in `harness.yaml`, never for the registry entry or the repo name:

1. **The shared library's `pdk-<id>` set** (`.sx/skills/linksets/pdk-<id>.txt`, for example
   `pdk-ihp-sg13g2`), for a process the shared library has a knowledge base for.
2. **A private per-kit library**, for a kit under NDA whose skill (rule digest, layout shortcuts,
   journal) may live only in the private repo that owns the kit. `$SX_KIT_SKILLS` names a clone of
   it; that library ships `linksets/pdk.txt`, and this script runs
   `sx-link . --library $SX_KIT_SKILLS --set pdk`. Each link it makes is a path into a per-machine
   clone of a private repo, so its `.claude/` path is also written to this clone's
   `info/exclude`: it is never committed (`make skills-update` stages `.claude`).

**One PDK id.** The declared value is looked up as the harness's ratified id first
(`spicexplorer_harness.fleet.pdk_id`: a registry token such as `ihp130` becomes `ihp-sg13g2`) and
then as written, then as each registry token of that id (a private kit library names its skill
`pdk-<token>`), so a design that declares either spelling gets the same set. `make lint` warns
when the declaration is a registry token rather than the ratified id. The ratified id comes from
the harness itself, never from a copy of its table here: from the installed package when there is
one, else from `.sx/platform`'s `fleet.py` (`make init` runs this before `uv sync`); when neither
can be read, the id is used as written.

The cases:

- `pdk:` is absent or empty: nothing is linked and nothing is printed.
- the shared library has the set: `sx-link . --set pdk-<id>`.
- the shared library has no set and `$SX_KIT_SKILLS` is unset: one INFO line, exit 0.
- `$SX_KIT_SKILLS` is set: its `pdk` set is linked as well; a clone that has no
  `linksets/pdk.txt` is an error (exit 2), because a configured library that links nothing would
  pass silently.

Standard library only: `make init` runs this before `uv sync` has made the venv, so PyYAML may not
be importable. `declared` reads one top-level `key:` line; a test checks that it agrees with the
harness's own loader on this repo's `harness.yaml`.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[1]

KIT_SKILLS_ENV = "SX_KIT_SKILLS"
#: the link set a private per-kit library ships
PRIVATE_SET = "pdk"
_FLEET = Path(".sx/platform/packages/spicexplorer-harness/src/spicexplorer_harness/fleet.py")
# What an id may be spelled with; anything else is not used to build a file name.
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_NULL = ("", "~", "null", "Null", "NULL")


def declared(harness_text: str, key: str) -> str:
    """The value of the top-level `key:` (no indentation, so a nested key of the same name does
    not count), or "" when it is absent, empty or null."""
    m = re.search(rf"^{re.escape(key)}:[ \t]*(.*?)[ \t]*$", harness_text, re.MULTILINE)
    if not m:
        return ""
    value = m.group(1)
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        return value[1:end] if end > 0 else ""
    value = re.split(r"[ \t]#", value, maxsplit=1)[0].strip()
    return "" if value in _NULL or value.startswith("#") else value


def declared_pdk(harness_text: str) -> str:
    """The value of the top-level `pdk:` key, or "" when it is absent, empty or null."""
    return declared(harness_text, "pdk")


def _harness_fleet(root: Path) -> ModuleType | None:
    """`spicexplorer_harness.fleet`: installed, else loaded from `.sx/platform`, else None."""
    try:
        from spicexplorer_harness import fleet
    except ImportError:
        pass
    else:
        return fleet
    path = root / _FLEET
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_sx_fleet_for_pdk_links", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (ImportError, OSError, SyntaxError):
        return None
    return module


def ratified(pdk: str, root: Path = REPO) -> str:
    """The harness's ratified id for `pdk`, or `pdk` as written when the harness is unreadable."""
    fleet = _harness_fleet(root)
    fn = getattr(fleet, "pdk_id", None)
    return str(fn(pdk)) if callable(fn) and pdk else pdk


def spellings(pdk: str, root: Path = REPO) -> list[str]:
    """The ids `pdk` is looked up as: the ratified id, the declared spelling, then each registry
    token the harness ratifies to the same id (a private kit library names its skill after the
    registry token, `pdk-<token>`)."""
    rid = ratified(pdk, root)
    table = getattr(_harness_fleet(root), "PDK_IDS", None)
    tokens = sorted(k for k, v in table.items() if v == rid) if isinstance(table, dict) else []
    out: list[str] = []
    for p in (rid, pdk, *tokens):
        if p and _ID.match(p) and p not in out:
            out.append(p)
    return out


def linkset(root: Path, pdk: str) -> str | None:
    """`pdk-<id>` when the library at `<root>/.sx/skills` ships that link set for a spelling of
    `pdk` (:func:`spellings`), else None."""
    for p in spellings(pdk, root):
        name = f"pdk-{p}"
        if (root / ".sx" / "skills" / "linksets" / f"{name}.txt").is_file():
            return name
    return None


def private_library(env: Mapping[str, str] | None = None) -> Path | None:
    """The private per-kit library `$SX_KIT_SKILLS` names, or None when it is unset."""
    value = (os.environ if env is None else env).get(KIT_SKILLS_ENV, "").strip()
    return Path(value).expanduser() if value else None


def private_entries(lib: Path) -> list[str]:
    """The entries of `lib/linksets/pdk.txt` (`skills/<name>`, `agents/<name>`), comments and
    blank lines dropped, as `sx-link` reads them."""
    text = (lib / "linksets" / f"{PRIVATE_SET}.txt").read_text()
    entries = (ln.split("#", 1)[0].strip() for ln in text.splitlines())
    return [e for e in entries if e]


def link_paths(entries: list[str]) -> list[str]:
    """The repo-relative `.claude/` path `sx-link` writes for each entry."""
    out = []
    for e in entries:
        kind, _, name = e.partition("/")
        if kind == "agents" and name:
            out.append(f".claude/agents/{name}.md")
        elif kind == "skills" and name:
            out.append(f".claude/skills/{name}")
    return out


def needs_private(lane: str, pdk: str, root: Path = REPO) -> bool:
    """True when the design's kit skills can only come from a private library: a commercial-kit
    lane (`lane: bridge`), a declared `pdk:` and no shared `pdk-<id>` set for it."""
    return lane == "bridge" and bool(pdk) and linkset(root, pdk) is None


def exclude(root: Path, paths: list[str]) -> Path | None:
    """Add `paths` (repo-relative, written anchored) to this clone's `info/exclude`; returns that
    file, or None when `root` is not a git checkout. A linked worktree shares its repository's."""
    r = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", "info/exclude"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode:
        return None
    path = Path(r.stdout.strip())
    if not path.is_absolute():
        path = root / path
    have = path.read_text().splitlines() if path.is_file() else []
    new = [f"/{p}" for p in paths if f"/{p}" not in have]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        block = ["# private per-kit skill links (scripts/pdk_links.py): never committed", *new]
        path.write_text("\n".join([*have, *block]) + "\n")
    return path


def _sx_link(root: Path, *args: str) -> int:
    tool = root / ".sx" / "skills" / "bin" / "sx-link"
    return subprocess.run([str(tool), str(root), *args], check=False).returncode


def link_private(root: Path, lib: Path) -> int:
    """Link `lib`'s `pdk` set into `root` and keep each link out of commits."""
    if not (lib / "linksets" / f"{PRIVATE_SET}.txt").is_file():
        print(
            f"ERROR: {KIT_SKILLS_ENV}={lib} has no linksets/{PRIVATE_SET}.txt: point it at a clone "
            "of the kit's private skill library, or unset it"
        )
        return 2
    # excluded BEFORE the links exist, so no window leaves them stageable
    exclude(root, link_paths(private_entries(lib)))
    return _sx_link(root, "--library", str(lib), "--set", PRIVATE_SET)


def main(root: Path = REPO, env: Mapping[str, str] | None = None) -> int:
    try:
        text = (root / "harness.yaml").read_text()
    except OSError:
        return 0
    pdk = declared_pdk(text)
    if not pdk:
        return 0
    rc = 0
    name = linkset(root, pdk)
    lib = private_library(env)
    if name is not None:
        rc = _sx_link(root, "--set", name)
    elif lib is None:
        print(
            f"INFO: harness.yaml declares pdk: {pdk}; the library at .sx/skills has no "
            f"linksets/pdk-{pdk}.txt and {KIT_SKILLS_ENV} is unset, so no per-PDK skill is linked"
        )
    if lib is not None:
        rc = link_private(root, lib) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
