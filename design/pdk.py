"""Where the process lives: WHICH model library, and which of its sections a deck includes.

Used by the bridge lane (`lane: bridge`, `design/sim_bridge.py`). The open lane resolves its
models through the PDK's own init file and never imports this module.

**Template code with four things to fill in** — `REVISION`, `SECTIONS`, the design tag in
`LIB_ENV_SCOPED` and the variable name in `LIB_ENV` — and a fifth, `MODEL_GROUPS`, that is
optional but arms a lint (`deck-models`) nothing else in this repo can do. Everything below them is the mechanism, and
it is identical in every commercial-PDK design; it is here rather than copied between designs
because the copies had already diverged, and a bug in a copied mechanism is a bug with N fixes
(MacAnalog/macanalog-design-directory#46).

Four consequences of the design worth stating once:

1. **A deck never contains the path.** It names `TOKEN` and pins the revision by name in its
   header; `sim.run` calls `restore()` to substitute the real path in as it hands the deck to the
   simulator. Every consumer that treats a deck as a DOCUMENT — the builder, the byte-for-byte
   `deck-rebuild` lint, `make freeze`'s sha-lock, `git diff` — therefore sees portable text, which
   is the only reason a certified deck can be committed at all. Redact-on-write with
   restore-on-read does NOT work in its place: the rebuild lint compares bytes, so every redacted
   bench stops reproducing.
2. **The path is per MACHINE, and it comes from the environment — never from a scan.** Three
   variables are read, in order, and `doc/environment.md` documents the machine-level one for the
   lab's per-account env file. Earlier designs recovered the path by grepping a NEIGHBOURING
   clone's committed deck; that route depends on which neighbours a person happens to have cloned,
   it resolves relative to the checkout so it breaks inside a git worktree, and it made the library
   that produced a number depend on an unrecorded local layout. It is deliberately not shipped.
3. **The revision pin binds on EVERY route**, including the environment one. A scorecard measured
   against another revision is not comparable, and the revision is the one input to reproducing it
   that a design deliberately does not commit — so an unchecked route turns one wrong export into
   a full green `make check` against a different process, recorded nowhere but the shell that ran
   it (MacAnalog/macanalog-design-directory#38). The escape hatch is typed, never silent.
4. **Sections are per device FAMILY, not one global corner.** A deck must include every section
   whose devices it instantiates; a missing one fails as an unresolved master, which reads like a
   typo rather than like a missing include. That failure arrives from the SIMULATOR — no gate in
   this repo simulates — unless `MODEL_GROUPS` below says which group each model belongs to, in
   which case `scripts/lint.py`'s `deck-models` catches it at lint time (template#36).

Nothing here writes the deck PREAMBLE — the language line, the temperature options, the title.
That is deck syntax and it belongs to `design/dut.py`, which calls `models_block()` for the
`include` lines. (One trap to carry into it: the temperature is an **options** statement. A
`parameters temp=…` line merely declares an unused netlist parameter, and the run silently uses
the simulator's default temperature — which makes a temperature sweep return byte-identical
results at every point. Pin `tnom` for the same reason.)

The value this module resolves is NEVER printed by it: callers put it in a deck, not in a log, a
doc or a note. Every message below names the VARIABLE and the revision, never the value.
"""

from __future__ import annotations

import os

from .sim import H

# ---------------------------------------------------------------- fill these in -------

# The model-library revision this design is pinned to, as `doc/environment.md` pins it. A NAME,
# not a path: the path is per machine and deliberately uncommitted.
REVISION = "<the model-library revision name, exactly as doc/environment.md pins it>"

# Sections BY WHAT THEY HOLD, so a deck says what it instantiates and this module owns the
# spelling. Keys are this design's vocabulary (`core`, `thick`, `res`, `mim`, `mismatch`); values
# are the section names the library spells. Add a row only once a run has resolved it: a guessed
# section fails as an unresolved master in whatever bench first uses it.
SECTIONS: dict[str, str] = {
    "core": "<the section holding this design's core devices>",
}

# Which SECTIONS group each DEVICE MODEL belongs to — `<the model name a deck instantiates>:
# <the key in SECTIONS above>`. Empty here, and empty is legal: the `deck-models` lint
# (`scripts/lint.py`) then prints one INFO line and checks nothing.
#
# Fill it and that lint becomes real: for every deck this design builds it finds each model name
# the deck instantiates and refuses a deck whose header does not include that model's section.
# The trap it exists for (template#36): a device was moved to another model flavour in a two-line
# netlist edit, two benches assembled their header from a fixed list of groups that did not
# include the new flavour's section, and `make lint`, `make test` and `make guard` were all green
# — nothing in this repo simulates, so the first thing that could see it was the simulator, and
# what it says is "unresolved master", which reads like a typo rather than a missing include.
#
# One row per model the benches instantiate; the value must be a key of SECTIONS.
MODEL_GROUPS: dict[str, str] = {
    # "<the model a deck instantiates>": "core",
}

# Corner labels. A corner is a prefix swap on the typical section names above (`tt_x` -> `ss_x`),
# which is why `section()` refuses to swap a section that does not start with the typical prefix:
# statistical sections are usually NOT corner-prefixed, and blindly swapping two characters asks
# for a section that does not exist — a loud failure whose message looks nothing like its cause.
CORNERS: tuple[str, ...] = ("tt", "ss", "ff", "sf", "fs")
TYPICAL = "tt"

# The variable whose NAME the deck text carries, spelled `$<name>` (see `TOKEN`). It is also the
# name every existing shell profile and `doc/environment.md` already uses, and it is the text
# inside every frozen deck — so renaming it forces a re-certify and a re-freeze of every reference.
LIB_ENV = "<PREFIX>_PDK_LIB"

# Read FIRST, and what a person should actually export: a name scoped to the DESIGN. `LIB_ENV` is
# scoped to a prefix at best, and prefixes are not unique across a design directory (two designs in
# this lab share one), so ONE export in ONE shell profile can feed two repos pinned to different
# revisions. A scoped export reaches this design and only this design.
LIB_ENV_SCOPED = "<DESIGNTAG>_PDK_LIB"

# ---------------------------------------------------------------- the mechanism -------


def machine_env() -> str:
    """The per-MACHINE variable name, derived from `pdk:` in `harness.yaml` (`""` if undeclared).

    The kit's install path is a property of the machine and of the KIT, not of the design: every
    design drawn in one process on one workstation wants the same value. So the last route is a
    variable named for the process — `ihp-sg13g2` -> `IHP_SG13G2_PDK_LIB`, the same grammar the
    lab's env file already uses for its other kit-keyed roots — set once per account and read by
    every design. It is derived rather than declared so that it cannot drift from `pdk:`.
    """
    pid = (getattr(H, "pdk", "") or "").strip()
    return "".join(c if c.isalnum() else "_" for c in pid).upper() + "_PDK_LIB" if pid else ""


def lib_envs() -> tuple[str, ...]:
    """The variables `library()` reads, in order: design-scoped, then the deck's name, then machine."""
    names = [LIB_ENV_SCOPED, LIB_ENV, machine_env()]
    return tuple(dict.fromkeys(n for n in names if n and not n.startswith("<")))


# What stands in for the library path in anything this repo COMMITS. Self-describing on purpose: a
# reader of a frozen deck sees the NAME of the variable that supplies the path, and the deck header
# above it pins the revision — which is what makes the deck reproducible without carrying the path.
TOKEN = f"${LIB_ENV}"

__all__ = ["REVISION", "SECTIONS", "MODEL_GROUPS", "CORNERS", "TYPICAL", "LIB_ENV", "LIB_ENV_SCOPED", "TOKEN",
           "PdkError", "machine_env", "lib_envs", "library", "restore", "section", "models_block",
           "unresolved"]


class PdkError(RuntimeError):
    """The process could not be located, or a deck asked for a section that is not real."""


def unresolved() -> str:
    """Why this design cannot bind to its process — `""` when it can. REPORTED, never raised.

    `make doctor` calls it before simulating anything: the probe deck is one resistor and would
    pass without the kit, but a lane that cannot bind this design to its model library is not
    alive. Names variables and placeholders, never a value.
    """
    if REVISION.startswith("<"):
        return ("design/pdk.py still carries the template's REVISION placeholder — set it to the "
                "model-library revision doc/environment.md pins")
    if any(v.startswith("<") for v in SECTIONS.values()) or not SECTIONS:
        return ("design/pdk.py still carries the template's SECTIONS placeholder — map this "
                "design's device groups onto the library's section names")
    names = lib_envs()
    if not names:
        return ("design/pdk.py names no model-library variable: set LIB_ENV / LIB_ENV_SCOPED (and "
                "declare `pdk:` in harness.yaml for the per-machine one)")
    if not any((os.environ.get(n) or "").strip() for n in names):
        return (f"the model library is unset: export one of {' / '.join(names)} to the path it "
                f"stands for (per machine, never committed; doc/environment.md pins WHICH library "
                f"by revision name)")
    return ""


def library() -> str:
    """The model library to `include`, as an absolute path ON THE MACHINE THAT HOLDS IT.

    Three variables, read in order — the design-scoped name, the name the frozen decks carry, and
    the per-machine one derived from `pdk:`. Whichever supplies it, **the value must carry
    `REVISION`**: a silent change of model library invalidates every certified number, and this is
    the one route every deck takes. A deliberate cross-revision run is still possible — it has to
    be TYPED (`<NAME>_ALLOW_MISMATCH=1`), so it is visible in the shell that ran it and in any
    recorded command, which is the whole difference between a one-off and a substitution.

    Never prints the value: the message names the variable and the revision.
    """
    names = lib_envs()
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if not value:
            continue
        if REVISION not in value and not any(
                os.environ.get(f"{n}_ALLOW_MISMATCH") for n in names):
            raise PdkError(
                f"{name} points at a library that is not this design's pinned revision "
                f"({REVISION}). Re-pin REVISION and doc/environment.md together, or set "
                f"{name}_ALLOW_MISMATCH=1 for a deliberate one-off — a silent revision change "
                f"invalidates every certified number.")
        return value
    raise PdkError(
        f"cannot locate the model library for revision {REVISION}: export {names[0] if names else LIB_ENV_SCOPED}"
        f" to it{'' if len(names) < 2 else ' (or ' + ' / '.join(names[1:]) + ')'}, or re-pin "
        f"REVISION and doc/environment.md together. None of these is set, and nothing is scanned "
        f"for: the path is per machine, so it comes from the environment — doc/environment.md says "
        f"which file the lab keeps it in.")


def restore(deck: str) -> str:
    """A portable deck made simulatable: `TOKEN` -> the library path, resolved on THIS machine.

    Called by `sim.run` and nowhere else. A deck carrying no token passes through untouched and
    `library()` is never called — a gm/ID extraction that builds its own include line through the
    platform's extractor must not be rewritten here.
    """
    return deck.replace(TOKEN, library()) if TOKEN in deck else deck


def section(group: str, corner: str = TYPICAL) -> str:
    """The section name for one device group at one corner."""
    if group not in SECTIONS:
        raise PdkError(f"unknown section group {group!r}; known: {sorted(SECTIONS)}")
    if corner not in CORNERS:
        raise PdkError(f"unknown corner {corner!r}; known: {list(CORNERS)}")
    s = SECTIONS[group]
    # ONLY the typical sections carry a corner prefix; a statistical section does not, and
    # swapping its first characters would ask for a section that does not exist.
    if corner == TYPICAL or not s.startswith(TYPICAL):
        return s
    return corner + s[len(TYPICAL):]


def models_block(corner: str = TYPICAL, *groups: str) -> str:
    """The `include` lines binding a deck to the kit at `corner` (default: every declared group).

    They name `TOKEN`, never the path — see the module docstring. Called from `design/dut.py`,
    which owns the rest of the preamble.
    """
    want = groups or tuple(SECTIONS)
    return "\n".join(f'include "{TOKEN}" section={section(g, corner)}' for g in want)
