#!/usr/bin/env python3
"""`make lint`: the generic harness checks (driven by harness.yaml) plus this repo's own.

Both template instantiations independently wrote the same two extra checks, so they ship here:
`deck_rebuild` (a frozen deck must still be reproducible from `design/` + its `design.json`) and
`spec_quotes` (the reference column of `doc/target-spec.md` must quote the certified scorecard).
Both no-op until something is certified, so `make lint` is green on a bare template.

Add this design's own `def check(L: Lint) -> None` and name it in EXTRA. A check earns its place
when a trap has bitten twice (`doc/journal/gap-as-signal.md`); its message carries the fix.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from spicexplorer_harness import lint, load  # noqa: E402
from spicexplorer_harness.lint import Lint  # noqa: E402

# The design package: `design/` in the bare template, renamed per instance (`ldo/`, `mzm_tx/`).
# It cannot live in harness.yaml yet — the platform loader rejects unknown keys, so a `package:`
# key needs a `Harness` field first (platform follow-up, noted in harness.yaml).
PACKAGE = "design"

# How a certified number may be written in doc/target-spec.md; any one match passes.
QUOTE_FORMATS = ("{:.4g}", "{:.3g}", "{:g}", "{:.3f}", "{:.2f}", "{:.1f}", "{:.0f}")


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
            from design.dut import Design
            point = Design.from_dict(json.loads((d / "design.json").read_text()))
            built = {b: point.deck(b) for b in point.benches()}
        except NotImplementedError:
            return  # a bare template: Design.deck is still the stub
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
    doc = h.text(h.spec_doc).replace("**", "")
    for row in h.spec:
        v = card.get(row.key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v:
            continue
        written = [f.format(v) for f in QUOTE_FORMATS]
        if not any(t in doc or t.replace("-", "−") in doc for t in written):
            L.fail("spec-sync",
                   f"certified {row.key} = {v:.4g} is not quoted in {h.spec_doc}",
                   f"the spec table's reference-baseline column quotes {h.reference_scorecard}; "
                   f"copy the certified number across (e.g. `{written[0]}`), or re-certify")


def package_importable(L: Lint) -> None:
    """`PACKAGE` names a real, importable package: the rename at instantiation is easy to
    half-finish, and every doc line, agent definition and Makefile target points at the name."""
    import importlib

    if not (L.h.root / PACKAGE / "__init__.py").is_file():
        L.fail("package", f"scripts/lint.py PACKAGE = {PACKAGE!r} but {PACKAGE}/__init__.py is missing",
               f"`git mv <old> {PACKAGE}` (or point PACKAGE at the real directory) — the design "
               "package is named for the DESIGN, and CLAUDE.md, the Makefile and every doc cite it")
        return
    try:
        importlib.import_module(PACKAGE)
    except Exception as exc:  # noqa: BLE001
        L.fail("package", f"`import {PACKAGE}` fails: {exc!r}",
               f"fix the package's imports; `make doctor`, `make test` and every experiment "
               f"start with `from {PACKAGE} import …`")


EXTRA = (package_importable, deck_rebuild, spec_quotes)

if __name__ == "__main__":
    sys.exit(lint.main(load(REPO), extra=EXTRA))
