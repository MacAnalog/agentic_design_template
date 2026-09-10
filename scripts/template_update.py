#!/usr/bin/env python3
"""`make template-status` / `make template-update`: keep a design in step with the template it was
cut from.

A design is **copied** from `agentic_design_template`, not submoduled to it, so it cannot pull.
What it carries instead is `.sx/template-version` — `MAJOR.MINOR` (`1.01`) — written by the
template and inherited by every repo created from it. The template tags each release `vMAJOR.MINOR`
and says in `CHANGELOG.md` what changed:

* **minor** (`1.00 -> 1.01`): generic work — a new module in the package, a lint check, a hook in
  the lane, docs. Propagatable into a design that is already under way: that is what `update` does.
* **major** (`1.x -> 2.0`): the scaffold's shape changed. `update` refuses to cross it and prints
  the changelog instead; crossing one is a deliberate, human-reviewed migration.

How `update` propagates without clobbering the design: it fetches the template as a remote (so the
preimage blobs exist locally), builds the diff between the recorded tag and the target tag, and
applies it with a **three-way merge**. A file the design never touched moves cleanly; a file the
design edited merges, or leaves conflict markers where a human must choose. Nothing is committed.

The one thing to know: the instantiation rename (`git mv design <package>`). The template's package
is `design/`; this design's is whatever `harness.yaml` says. So the diff is applied in two parts —
the package part relative to `design/`, re-rooted onto `<package>/`, and everything else as it is.
That rewrites the PATHS a hunk lands on, never a hunk's CONTENT: a template line that imports
`design.metrics` arrives spelled that way, so run `make lint && make test` afterwards and fix what
the report lists.

    scripts/template_update.py status          # recorded vs latest release
    scripts/template_update.py update [VER]    # propagate up to VER (default: latest minor)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO / ".sx" / "template-version"
REMOTE = "template"
URL = "https://github.com/MacAnalog/agentic_design_template.git"
VER_RE = re.compile(r"^(\d+)\.(\d{2})$")

# Never propagated: what a design owns the moment it is instantiated. Everything else — including a
# module the template grows later — comes across, and the three-way merge protects local edits.
EXCLUDE = (
    ":!harness.yaml",          # this design's spec, benches, denylist
    ":!README.md",
    ":!doc",                   # the design's own reference/journal/spec prose
    ":!pdf",
    ":!uv.lock",
    ":!pyproject.toml",        # its dependency set (the template's is a starting point)
    ":!.sx/skills",            # the library pin: `make skills-update` owns it
    ":!.sx/template-version",  # written here, at the end
    ":!experiments",           # `experiments/_template/` included: a design edits its own copy
    ":!decks",
    ":!layout",
)
# Inside the package, only the topology is purely the design's: the template's `dut.py` is a stub, so
# propagating its changes into a real one is conflict noise and nothing else. Everything else in the
# package — `metrics.py` (the scorecard lifecycle around a design-specific KEYMAP), `bench.py` (the
# reduction hook), `sim.py` (the lane wrapper around a design-specific policy), `exp.py`, `plot.py`,
# `stimulus.py` — is generic work the design SHOULD receive; the three-way merge is what protects
# the design-specific lines inside them, and a conflict there is a decision, not a failure.
PKG_EXCLUDE = (":!dut.py",)


def sh(*args: str, cwd: Path = REPO, check: bool = True) -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"$ {' '.join(args)}\n{r.stdout}{r.stderr}")
    return r.stdout


def recorded() -> str:
    if not VERSION_FILE.is_file():
        raise SystemExit(
            f"{VERSION_FILE.relative_to(REPO)} is missing — this design predates template "
            f"versioning. Write the version it was cut from (e.g. `echo 1.00 > "
            f"{VERSION_FILE.relative_to(REPO)}`) and commit it; `status` then works. If you do not "
            f"know, 1.00 is the first tagged release: a later `update` may raise conflicts you "
            f"resolve by hand, never a silent overwrite.")
    v = VERSION_FILE.read_text().strip()
    if not VER_RE.match(v):
        raise SystemExit(f"{VERSION_FILE.relative_to(REPO)} holds {v!r}; expected MAJOR.MINOR, e.g. 1.01")
    return v


def package() -> str:
    for line in (REPO / "harness.yaml").read_text().splitlines():
        if line.startswith("package:"):
            return line.split(":", 1)[1].split("#")[0].strip()
    raise SystemExit("harness.yaml has no `package:` line")


def fetch() -> list[str]:
    """Add/refresh the template remote and return its release versions, oldest first."""
    if REMOTE not in sh("git", "remote").split():
        sh("git", "remote", "add", REMOTE, URL)
    sh("git", "fetch", "--quiet", "--tags", REMOTE)
    tags = [t[1:] for t in sh("git", "tag", "--list", "v*").split() if VER_RE.match(t[1:])]
    return sorted(tags, key=lambda v: tuple(int(x) for x in v.split(".")))


def latest_minor(cur: str, tags: list[str]) -> str | None:
    major = cur.split(".")[0]
    same = [t for t in tags if t.split(".")[0] == major and t > cur]
    return same[-1] if same else None


def changelog(a: str, b: str) -> str:
    try:
        text = sh("git", "show", f"v{b}:CHANGELOG.md", check=False)
    except SystemExit:
        return ""
    keep, out = False, []
    for line in text.splitlines():
        if line.startswith("## "):
            ver = line.split()[1].lstrip("v")
            keep = VER_RE.match(ver) is not None and a < ver <= b
        if keep:
            out.append(line)
    return "\n".join(out)


def status() -> int:
    cur, tags = recorded(), fetch()
    if not tags:
        print(f"template {cur} recorded; the template has no release tags yet")
        return 0
    nxt, newest = latest_minor(cur, tags), tags[-1]
    print(f"template-version: {cur} (recorded)   latest release: {newest}")
    if nxt:
        print(f"MINOR updates available: {cur} -> {nxt}   run `make template-update`")
        print(changelog(cur, nxt) or "  (no changelog entries)")
    elif newest.split(".")[0] != cur.split(".")[0]:
        print(f"a MAJOR release exists ({newest}): a migration, not a propagation — read its "
              f"CHANGELOG.md entry and decide deliberately")
    else:
        print("up to date")
    return 0


def _apply_one(diff: str, directory: str | None) -> tuple[bool, str]:
    cmd = ["git", "apply", "--3way", "--whitespace=nowarn"]
    if directory:
        cmd += [f"--directory={directory}"]
    r = subprocess.run(cmd, cwd=REPO, input=diff, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def _apply(a: str, b: str, paths: list[str], directory: str | None = None,
           relative: str | None = None) -> list[tuple[str, str, str]]:
    """Apply the diff FILE BY FILE and report each one.

    `git apply` is atomic: one file the design does not have (a test module it dropped, a script it
    never received) aborts the whole patch and silently rolls back every file that HAD merged. So
    each file is applied on its own — a design gets everything that can land, and the report says
    exactly what did not.
    """
    base = ["git", "diff", "--full-index", f"v{a}", f"v{b}"]
    base += [f"--relative={relative}"] if relative else []
    names = sh(*base, "--name-only", "--", *paths).split()
    out: list[tuple[str, str, str]] = []
    for name in names:
        target = (Path(directory) / name) if directory else Path(name)
        diff = sh(*base, "--", (f"{relative}{name}" if relative else name))
        if not diff.strip():
            continue
        exists = (REPO / target).exists()
        ok, msg = _apply_one(diff, directory)
        if ok:
            out.append((str(target), "merged" if exists else "added", ""))
        elif not exists:
            out.append((str(target), "skipped", "this design does not carry the file the change edits"))
        else:
            out.append((str(target), "CONFLICT" if "conflict" in msg.lower() else "REJECTED", msg))
    return out


def update(target: str | None) -> int:
    cur, tags = recorded(), fetch()
    if not tags:
        print("the template has no release tags yet — nothing to propagate")
        return 0
    want = target or latest_minor(cur, tags)
    if not want:
        print(f"template {cur}: up to date")
        return 0
    if not VER_RE.match(want) or want not in tags:
        raise SystemExit(f"{want!r} is not a template release; tags: {', '.join(tags)}")
    if want.split(".")[0] != cur.split(".")[0]:
        print(f"REFUSED: {cur} -> {want} crosses a MAJOR version. The scaffold's shape changed, so "
              f"this is a migration, not a propagation:\n\n{changelog(cur, want)}\n\n"
              f"    FIX: follow the migration note, then write the new version into "
              f"{VERSION_FILE.relative_to(REPO)} yourself.")
        return 2
    pkg = package()
    print(f"template {cur} -> {want}   package: {pkg}\n{changelog(cur, want) or '(no changelog entries)'}\n")

    # 1) the package, re-rooted from the template's `design/` onto this design's package dir
    rows = _apply(cur, want, ["design/", *PKG_EXCLUDE], directory=pkg, relative="design/")
    # 2) everything else, path for path
    rows += _apply(cur, want, [".", ":!design", *EXCLUDE])

    width = max((len(r[0]) for r in rows), default=1)
    for name, verdict, msg in rows:
        print(f"  {name:<{width}}  {verdict}")
        if msg:
            print("      " + msg.replace("\n", "\n      "))
    if not rows:
        print("  (no files changed between these releases outside what this design owns)")
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(want + "\n")
    bad = [r for r in rows if r[1] in ("CONFLICT", "REJECTED")]
    print(f"\n.sx/template-version -> {want} (nothing is committed)")
    print("NOW: read every merged file, resolve each CONFLICT (they are decisions: the template's "
          "generic change meeting your design's own lines), then `make lint && make test`.")
    print("A hunk whose TEXT names the template's `design.` package arrives spelled that way — fix "
          "those by hand; that is why this prints a report instead of committing.")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="template_update")
    ap.add_argument("action", choices=("status", "update"))
    ap.add_argument("version", nargs="?", help="update: the release to go to (default: latest minor)")
    a = ap.parse_args(argv)
    return status() if a.action == "status" else update(a.version)


if __name__ == "__main__":
    sys.exit(main())
