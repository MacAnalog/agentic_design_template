"""The sizing point. Decks are built from it, never text-edited."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Design:
    topology: str = "<topology>"

    def deck(self) -> str:
        raise NotImplementedError("emit the testbench + DUT subckt for this sizing point")

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)
