#!/usr/bin/env python3
"""`make lint`: the generic harness checks (driven by harness.yaml) plus this repo's own.

Both template instantiations independently wrote the same two extra checks, so they ship here:
`deck_rebuild` (a frozen deck must still be reproducible from `design/` + its `design.json`) and
`spec_quotes` (the reference column of `doc/target-spec.md` must quote the certified scorecard).
`deck_portable` joins them on the same evidence — two designs froze a deck carrying a
machine-specific absolute library path. All three no-op until something is certified, so
`make lint` is green on a bare template.

Add this design's own `def check(L: Lint) -> None` and name it in EXTRA. A check earns its place
when a trap has bitten twice (`doc/journal/gap-as-signal.md`); its message carries the fix.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from spicexplorer_harness import lint, load  # noqa: E402
from spicexplorer_harness.lint import Lint  # noqa: E402

# How a certified number may be written in doc/target-spec.md; any one WHOLE-TOKEN match passes.
# Three significant figures minimum, on purpose: at `{:.0f}` a doc reading `62` would "quote" a
# certified 61.5 and 62.4 alike, and the drift check would pass the drift it exists to catch.
QUOTE_FORMATS = ("{:.4g}", "{:.3g}", "{:g}")
# fixed-point spellings a `g` format never emits (a doc may write 62.40 for a certified 62.4).
# Only at |v| >= 1: below that they are the imprecision this check exists to catch (`{:.2f}` of
# 0.001234 is `0.00`), and the unit-scaled-keys rule keeps scorecard values off that range anyway.
QUOTE_FIXED = ("{:.3f}", "{:.2f}")
NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
# An include/library line naming an ABSOLUTE path: what `deck_portable` refuses in a frozen deck.
# `$VAR` and repo-relative spellings are the portable forms and never match.
_ABS_INCLUDE = re.compile(r'^\s*\.?(?:include|lib)\b[^\n]*?["\'\s](/[^"\'\s]+)', re.I | re.M)


def _frozen_dirs(L: Lint) -> list[Path]:
    return [L.h.path(rel) for rel in L.h.frozen if (L.h.path(rel) / "design.json").is_file()]


def deck_rebuild(L: Lint) -> None:
    """Every frozen bench must still be byte-reproducible from `design.dut.Design` + `design.json`.

    The frozen `*.spice` are bytes; `design/dut.py` is their generator. If a bench template, a model
    pin or the deck builder drifts, every experiment silently measures a different bench than the
    certified one — and the drift is invisible, because the frozen bytes still hash correctly.
    """
    fix = ("a bench template, a submodule pin or design/dut.py changed: revert it, or re-certify "
           "deliberately (`make certify && make freeze`) — an un-reproducible reference means "
           "every A/B is measured against a bench nobody can rebuild")
    for d in _frozen_dirs(L):
        rel = d.relative_to(L.h.root).as_posix()
        try:
            # via `package:`, never `from design.dut import …`: the check that catches a
            # half-finished rename must not itself be broken BY the rename
            Design = importlib.import_module(f"{L.h.package}.dut").Design
            point = Design.from_dict(json.loads((d / "design.json").read_text()))
            built = {b: point.deck(b) for b in point.benches()}
        except NotImplementedError:
            continue  # a bare template: Design.deck is still the stub. `continue`, not `return`
        except ModuleNotFoundError as exc:
            L.fail("deck-rebuild", f"cannot import {L.h.package}.dut: {exc}",
                   f"harness.yaml says `package: {L.h.package}` — finish the rename (the package "
                   "dir, its imports, the Makefile, layout/signoff.py, experiments/_template/) "
                   "or point `package:` at the directory that exists")
            continue
        except Exception as exc:  # noqa: BLE001
            L.fail("deck-rebuild", f"cannot rebuild {rel} from its design.json: {exc!r}",
                   "design.json must round-trip through design.dut.Design.from_dict; "
                   "fix the loader or re-certify")
            continue
        for b, text in built.items():
            p = d / f"{b}.spice"
            if not p.exists():
                L.fail("deck-rebuild", f"{rel}/{b}.spice is missing", fix)
            elif p.read_text() != text:
                L.fail("deck-rebuild", f"design.dut.Design.deck({b!r}) no longer reproduces {rel}/{b}.spice", fix)


def abs_includes(text: str) -> list[str]:
    """Absolute paths named on a deck's include/library lines (`include`, `.include`, `.lib`)."""
    return [m.group(1) for m in _ABS_INCLUDE.finditer(text)]


def deck_portable(L: Lint) -> None:
    """A frozen deck may not carry an absolute path from the machine that certified it.

    Bitten twice, in two designs: a deck built with the model library's absolute path in its
    include line was frozen and committed, which makes the certified reference unusable on any
    other machine and hard-codes a path that may not be publishable at all. Redaction on write
    with restoration on read does not fix it — `deck_rebuild` above compares bytes, so every
    redacted bench stops reproducing. The pattern that works lives in `design/sim.py`: the deck
    text names `$VAR`, `sim.DECK_VARS` declares it, `sim.run` resolves it at the moment of
    simulating, and the committed bytes stay portable.
    """
    for d in _frozen_dirs(L):
        for p in sorted(d.glob("*.spice")):
            rel = p.relative_to(L.h.root).as_posix()
            for path in abs_includes(p.read_text(errors="replace")):
                L.fail("deck-portable", f"{rel} includes the absolute path {path}",
                       f"a frozen deck is committed, hashed and rebuilt byte for byte, so the "
                       f"path may not be in it: name it `$VAR` in the deck, declare VAR in "
                       f"`{L.h.package}.sim.DECK_VARS` (resolved in `sim.run`), re-certify "
                       f"(`make certify && make freeze`)")


def spec_quotes(L: Lint) -> None:
    """The reference-baseline column of `doc/target-spec.md` quotes the certified scorecard.

    A spec doc whose baseline column drifted from `reference_scorecard` invites every later
    comparison to be made against a number nobody measured.
    """
    h = L.h
    if not h.reference_scorecard:
        return
    try:
        card = json.loads(h.text(h.reference_scorecard))["scorecard"]
    except (ValueError, KeyError, TypeError):
        return
    doc = h.text(h.spec_doc).replace("**", "").replace("−", "-")
    # whole tokens, never a substring: `62` inside `1620` is not a quotation of 62, and a doc
    # that says `62` is not quoting a certified 62.4
    tokens = set(NUMBER.findall(doc))
    for row in h.spec:
        v = card.get(row.key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v:
            continue
        written = [f.format(v) for f in QUOTE_FORMATS]
        written += [f.format(v) for f in QUOTE_FIXED] if abs(v) >= 1 else []
        if not tokens.intersection(written):
            L.fail("spec-quotes",
                   f"certified {row.key} = {v:.4g} is not quoted in {h.spec_doc}",
                   f"the spec table's reference-baseline column quotes {h.reference_scorecard}; "
                   f"copy the certified number across (e.g. `{written[0]}`), or re-certify")


def sx_links(L: Lint) -> None:
    """`.sx/platform` is a platform checkout and every linked agent/skill resolves (`make init`).

    The platform packages install through `.sx/platform` and the shared agent/skill definitions
    are per-entry symlinks into the `.sx/skills` submodule; a checkout where either dangles runs
    with no harness or with no agents, silently. Both are per-checkout state, so `make init` is
    the fix in every case.
    """
    root = L.h.root
    plat = root / ".sx" / "platform"
    if not (plat / "packages" / "spicexplorer-harness" / "pyproject.toml").is_file():
        where = os.readlink(plat) if plat.is_symlink() else "missing"
        L.fail("sx-links", f".sx/platform does not resolve to a spicexplorer-platform checkout ({where})",
               "export SX_ROOT=<your spicexplorer-workspace checkout> (the lab: ~/.sx_env) and run `make init`")
    tool = root / ".sx" / "skills" / "bin" / "sx-link"
    if not tool.is_file():
        L.fail("sx-links", ".sx/skills (the analog-skill-directory submodule) is not initialised",
               "run `make init` (= git submodule update --init --recursive .sx/skills, then the links)")
        return
    r = subprocess.run([str(tool), str(root), "--set", "design", "--check"], capture_output=True, text=True)
    if r.returncode:
        first = next((ln for ln in r.stdout.splitlines() if ln and not ln.startswith(" ")), "links missing")
        L.fail("sx-links", first.strip(), "run `make init` (re-links every entry from .sx/skills; a "
               "nested submodule needs the --recursive it does)")


# Where a committed artefact is allowed to live (template 2.00, "every artefact has a home").
# A figure or a table is evidence: it belongs beside the claim it supports, in a directory a reader
# can find without being told. Raw simulator output is the opposite — it stays in the scratch root
# and is never committed at all.
ARTIFACT_SUFFIXES = (".png", ".svg", ".pdf", ".csv", ".gds", ".gds.gz")
# ADD THIS DESIGN'S OWN HOMES HERE, deliberately, one line each with why. That is the whole
# escape hatch and it is on purpose: a home nobody wrote down is a directory the next reader has
# to guess at, and a one-line declaration in a reviewed file costs nothing.
ARTIFACT_HOMES = (
    "signoff/",        # the design of record, by fidelity — what a reader is entitled to trust
    "experiments/",    # the working space: agents organize inside it freely (figs/ + tables/ is the habit)
    "layout/",         # the generator's own working output; what is SIGNED OFF moves to signoff/layout/
    "decks/",          # candidate and control deck dirs (the CERTIFIED ones live in signoff/)
    "references/",     # papers, datasheets, standards
    "doc/",            # figures that belong to a document
    "notebooks/",      # executed in place, outputs committed
    ".claude/", ".sx/", ".github/",
)


def artifact_home(L: Lint) -> None:
    """Every committed figure, table or layout sits in a home this repo has declared.

    An agent that leaves a plot in whichever directory it was standing in produces a repo nobody
    can read six weeks later, and a reviewer who cannot find the evidence treats the claim as
    unsupported. The check is not about tidiness: it is about whether the evidence is findable.

    It is deliberately not a straitjacket. `experiments/` is wide open — that IS the working space
    — and a design with its own durable output directory adds one line to `ARTIFACT_HOMES` above.
    What it refuses is the undeclared case: an artefact somewhere nobody wrote down.
    """
    root = L.h.root
    r = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True)
    if r.returncode:
        return  # not a git checkout (a template copied by hand): nothing to check
    # Grouped by top-level directory, because that is the unit you DECLARE. Reporting one failure
    # per file would print 248 blocks on a design with a physics lane, and a lint nobody can read
    # is a lint that gets switched off. `dict` keeps first-seen order; it also dedupes the stages
    # `git ls-files` emits for an unmerged path mid-merge.
    stray: dict[str, list[str]] = {}
    for rel in dict.fromkeys(r.stdout.split("\0")):
        if not rel or not rel.endswith(ARTIFACT_SUFFIXES) or (root / rel).is_symlink():
            continue
        if rel.startswith(ARTIFACT_HOMES):
            continue
        stray.setdefault(rel.split("/")[0] + "/" if "/" in rel else "(repo root)", []).append(rel)
    for where, files in stray.items():
        eg = files[0] if len(files) == 1 else f"{len(files)} files, e.g. {files[0]}"
        L.fail("artifact-home", f"{where} holds committed artefacts outside every declared home "
                                f"({eg})",
               f"either MOVE them — an experiment's evidence to `experiments/NNN-*/figs|tables/`, "
               f"a measured result to `signoff/<fidelity>/`, a document's figure to `doc/`, a "
               f"paper to `references/` — or DECLARE `{where}` in `ARTIFACT_HOMES` in this file, "
               f"with one line saying what lives there. Raw simulator output is neither: it is "
               f"never committed, and stays in the scratch root ($SX_SCRATCH)")


def signoff_index(L: Lint) -> None:
    """Every directory under `signoff/` is named in `signoff/README.md`.

    `signoff/` is the tree a reader trusts, so an unlisted directory in it is worse than no
    directory: it looks certified and says nothing about the conditions it was measured under.
    The README's table is the index — one row per fidelity, with its scorecard and its status.
    """
    d = L.h.root / "signoff"
    if not d.is_dir():
        return  # a design that has not started signing anything off
    idx = d / "README.md"
    if not idx.is_file():
        L.fail("signoff-index", "signoff/ exists but signoff/README.md does not",
               "copy it from the template (`make template-update`): it is the index of what is "
               "signed off, at which fidelity, by whom and when")
        return
    text = idx.read_text()
    # `__pycache__` and dot-dirs are tooling debris, not fidelities: they are not sign-offs and
    # demanding a README row for them would teach people to ignore this check.
    subs = (p.name for p in d.iterdir()
            if p.is_dir() and not p.name.startswith(".") and p.name != "__pycache__")
    for sub in sorted(subs):
        if f"`{sub}`" not in text and f"`{sub}/" not in text:
            L.fail("signoff-index", f"signoff/{sub}/ is not named in signoff/README.md",
                   f"add a row for `{sub}` to the table — what the number includes, its scorecard "
                   f"path, its status, who signed it and when. A fidelity nobody described is not "
                   f"a sign-off")


# `package-importable` is NOT here: the platform ships it (driven by `package:` in harness.yaml).
EXTRA = (deck_rebuild, deck_portable, spec_quotes, sx_links, artifact_home, signoff_index)

if __name__ == "__main__":
    sys.exit(lint.main(load(REPO), extra=EXTRA))
