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

import importlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from spicexplorer_harness import lint, load  # noqa: E402
from spicexplorer_harness.lint import Lint  # noqa: E402

# How a certified number may be written in doc/target-spec.md; any one WHOLE-TOKEN match passes.
# Three significant figures minimum, on purpose: at `{:.0f}` a doc reading `62` would "quote" a
# certified 61.5 and 62.4 alike, and the drift check would pass the drift it exists to catch.
QUOTE_FORMATS = ("{:.4g}", "{:.3g}", "{:g}", "{:.3f}", "{:.2f}")
NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


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
        if not tokens.intersection(written):
            L.fail("spec-quotes",
                   f"certified {row.key} = {v:.4g} is not quoted in {h.spec_doc}",
                   f"the spec table's reference-baseline column quotes {h.reference_scorecard}; "
                   f"copy the certified number across (e.g. `{written[0]}`), or re-certify")


# `package-importable` is NOT here: the platform ships it (driven by `package:` in harness.yaml).
EXTRA = (deck_rebuild, spec_quotes)

if __name__ == "__main__":
    sys.exit(lint.main(load(REPO), extra=EXTRA))
