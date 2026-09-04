"""The sizing point. Decks are built from it, never text-edited.

One `Design` renders EVERY bench of the design (`benches()` → `deck(bench)`): both
instantiations turned out to be multi-bench, and `design.metrics`, the `deck-rebuild` lint and
`certify()` are all written against that pair. A single-bench design returns a one-element
list. `as_dict`/`from_dict` must round-trip, because `design.json` beside a frozen deck is
what proves the frozen bytes are still reproducible from this code.
"""

from __future__ import annotations

import dataclasses

BENCHES: tuple[str, ...] = ("<bench>",)  # the analyses this design is scored on, in report order


@dataclasses.dataclass(frozen=True)
class Design:
    topology: str = "<topology>"

    def benches(self) -> list[str]:
        """The benches `design.metrics` builds a deck for (a design bound to a circuit database
        returns that circuit's declared analyses instead of this constant)."""
        return list(BENCHES)

    def deck(self, bench: str) -> str:
        """The complete ngspice deck for one bench: `*` title line first, DUT + bench, its own
        `.control` block (`print`/`meas` scalars for `design.metrics.promote`, and/or `write sim.raw`).

        Build it — never text-edit a generated deck. Where a template engine already emits the
        bench, append the sizing as a trailing `.param` block instead of editing its lines.
        """
        raise NotImplementedError(f"emit the testbench + DUT subckt for {bench!r}")

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Design":
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in fields})


REFERENCE = Design()  # the point `make certify` freezes and `make check` re-measures
