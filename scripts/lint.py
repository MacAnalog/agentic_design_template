#!/usr/bin/env python3
"""`make lint`: the generic harness checks (driven by harness.yaml) plus this repo's own.

Both template instantiations independently wrote the same two extra checks, so they ship here:
`deck_rebuild` (a frozen deck must still be reproducible from `design/` + its `design.json`) and
`spec_quotes` (the reference column of `doc/target-spec.md` must quote the certified scorecard).
`deck_portable` joins them on the same evidence — two designs froze a deck carrying a
machine-specific absolute library path. All three no-op until something is certified, so
`make lint` is green on a bare template. Two more came from the same place: `deck_models` (a deck
that instantiates a device model must include that model's section — the one deck defect only a
simulator could see) and `scratch_budget` (soft: a work dir over the warn mark whose biggest
records nothing has reduced).

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

from scripts import githook  # noqa: E402
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


# A model name as a deck writes it: whole token only, so `nmos_a` is not found inside `nmos_a_hv`
# and a group name that happens to be a substring of another never matches.
def _token(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![0-9A-Za-z_]){re.escape(name)}(?![0-9A-Za-z_])")


# The header lines a section can be declared on, and the section each one names.
_SECTION_OF = re.compile(r'^\s*\.?(?:include|lib)\b[^\n]*?\bsection\s*=\s*["\']?([A-Za-z0-9_.-]+)',
                         re.I | re.M)
_INCLUDE_LINE = re.compile(r'^\s*\.?(?:include|lib)\b', re.I)
# Comment spellings both deck dialects use. `*` only in the first column, which is the SPICE rule.
_COMMENT_LINE = re.compile(r'^\s*(?:\*|//|;)|^\*')


def header_sections(deck: str) -> set[str]:
    """Every section name the deck's include/library lines pin (`include "$VAR" section=tt_core`)."""
    return {m.group(1) for m in _SECTION_OF.finditer(deck)}


def instantiating_body(deck: str) -> str:
    """The deck without its comments and its include/library lines — where a model is INSTANTIATED.

    The include lines are dropped so a section whose name happens to spell a model name cannot
    pass the check for it, and the comments so a model named in a note does not demand a section.
    """
    return "\n".join(ln for ln in deck.splitlines()
                     if not _COMMENT_LINE.match(ln) and not _INCLUDE_LINE.match(ln))


def _points(L: Lint) -> list[tuple[str, object]]:
    """The sizing points whose decks are checked: the same frozen `design.json`s `deck_rebuild`
    enumerates, plus `<package>.dut.REFERENCE`.

    The reference point is added because a design's FIRST deck-header omission happens long before
    it certifies anything, and a frozen-dirs-only enumeration checks exactly nothing until then.
    Deduped on `as_dict()`, so a repo whose frozen point IS the reference is checked once.
    """
    out: list[tuple[str, object]] = []
    seen: list[dict] = []
    try:
        dut = importlib.import_module(f"{L.h.package}.dut")
    except Exception:  # noqa: BLE001 - `deck_rebuild` owns the reporting of a broken package
        return out
    for d in _frozen_dirs(L):
        try:
            point = dut.Design.from_dict(json.loads((d / "design.json").read_text()))
        except Exception:  # noqa: BLE001 - `deck_rebuild` reports an unloadable design.json
            continue
        out.append((d.relative_to(L.h.root).as_posix(), point))
    ref = getattr(dut, "REFERENCE", None)
    if ref is not None:
        out.append((f"{L.h.package}.dut.REFERENCE", ref))
    kept = []
    for where, point in out:
        try:
            key = point.as_dict()
        except Exception:  # noqa: BLE001
            key = None
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.append(key)
        kept.append((where, point))
    return kept


def deck_models(L: Lint) -> None:
    """A deck that instantiates a device model includes that model's section in its header.

    The one class of deck defect no other gate in this repo can see (template#36). A design moved
    one device to another model flavour — a two-line netlist edit — and two benches went on
    assembling their header from a fixed list of model groups that did not include the new
    flavour's section. `make lint` (20 invariants), `make test` (47) and `make guard` were all
    green, because nothing here simulates: the first thing able to notice was the simulator, whose
    verdict is `unresolved master`, which reads like a typo in a device line rather than like a
    missing include.

    It is string-level on text the design already generates, so it costs nothing: for every deck
    the design builds, each model named in `<package>.pdk.MODEL_GROUPS` that appears in the deck
    BODY must have one of its section's corner spellings on an include line of the deck HEADER.

    Three ways it stays quiet rather than wrong: a design with no `pdk` module is skipped
    silently; a design whose `MODEL_GROUPS` is still empty is skipped too, with one INFO line on
    the lane that has sections at all (`lane: bridge`) and nothing on the open lane, which
    resolves its models through the PDK's own init file; and the map is the design's to write, so
    an unfillable check is never a warning. INFO rather than `L.warn` on purpose: a warning would
    count against "all invariants hold" on every run of a design that has not got there yet.
    """
    try:
        pdk = importlib.import_module(f"{L.h.package}.pdk")
    except Exception:  # noqa: BLE001 - no pdk module (the open lane), or one that cannot import
        return
    groups: dict[str, str] = dict(getattr(pdk, "MODEL_GROUPS", {}) or {})
    if not groups:
        # The INFO is for the lane that HAS sections. Every copy of the template ships `pdk.py`,
        # so printing it on an open-lane design (whose models come from the PDK's own init file
        # and whose decks have no `section=` at all) would be a line nobody can ever act on.
        if str(getattr(L.h, "lane", "") or "") == "bridge":
            print(f"INFO: deck-models skipped — {L.h.package}/pdk.py MODEL_GROUPS is empty; fill "
                  f"it (model name -> SECTIONS group) and every deck's header is then checked "
                  f"against the models it instantiates")
        return
    corners = tuple(getattr(pdk, "CORNERS", ()) or (getattr(pdk, "TYPICAL", "tt"),))
    seen: set[tuple[str, str]] = set()
    for where, point in _points(L):
        try:
            benches = list(point.benches())
        except Exception:  # noqa: BLE001
            continue
        for bench in benches:
            try:
                deck = point.deck(bench)
            except NotImplementedError:
                continue                      # a bare template: `Design.deck` is still the stub
            except Exception:  # noqa: BLE001 - `deck_rebuild` reports a builder that raises
                continue
            have = header_sections(deck)
            body = instantiating_body(deck)
            for model, group in sorted(groups.items()):
                if not _token(model).search(body) or (bench, model) in seen:
                    continue
                seen.add((bench, model))
                try:
                    want = {pdk.section(group, c) for c in corners}
                except Exception as exc:  # noqa: BLE001 - an undeclared group is the same bug
                    L.fail("deck-models",
                           f"{bench}: instantiates {model} but MODEL_GROUPS maps it to the group "
                           f"{group!r}, which is not a section this design declares ({exc})",
                           f"add {group!r} to SECTIONS in {L.h.package}/pdk.py (the section name "
                           f"the library spells), or point MODEL_GROUPS[{model!r}] at a group "
                           f"that exists")
                    continue
                if not (have & want):
                    L.fail("deck-models",
                           f"{bench}: instantiates {model} but its header lacks the {group} "
                           f"section (header: {sorted(have) or 'no section= include line at all'}"
                           f"; from {where})",
                           f'add "{group}" to the pdk.models_block(...) call in '
                           f"{L.h.package}/dut.py that builds Design.deck({bench!r}) — the "
                           f"simulator's own verdict for this is `unresolved master`, which "
                           f"reads like a typo in the device line rather than a missing include")

_ID_LIKE = re.compile(r"\s*([A-Z]{1,3}\d{1,3})\b")   # `S3`, `A12`: how a spec table numbers its rows


def _row_lines(doc: str, row) -> list[str]:
    """The line(s) of the spec doc that name this row.

    Four spellings, most specific first: the row's `id:`, the `S3`-style id at the front of its
    label (how a pre-v2 design carries the same thing — `label: "S1 regulated output, no load"`),
    its key, its whole label. Whole tokens only, so `S1` does not match `S10` and `gain` does not
    match `gain_db_max`. The first spelling that hits anywhere wins.
    """
    label = getattr(row, "label", "") or ""
    m = _ID_LIKE.match(label)
    for token in (getattr(row, "id", "") or "", m.group(1) if m else "", row.key, label):
        if not token:
            continue
        pat = re.compile(rf"(?<![0-9A-Za-z_]){re.escape(token)}(?![0-9A-Za-z_])")
        hits = [ln for ln in doc.splitlines() if pat.search(ln)]
        if hits:
            return hits
    return []


def spec_quotes(L: Lint) -> None:
    """The reference-baseline column of `doc/target-spec.md` quotes the certified scorecard.

    A spec doc whose baseline column drifted from `reference_scorecard` invites every later
    comparison to be made against a number nobody measured.

    Matched PER ROW, against the doc line that names the row: a document-wide match passes a wrong
    baseline whenever the certified number appears anywhere else in the file, which in a spec doc
    (bounds, sample counts, dates, prose about earlier builds) is most of the time.
    """
    h = L.h
    if not h.reference_scorecard:
        return
    try:
        card = json.loads(h.text(h.reference_scorecard))["scorecard"]
    except (ValueError, KeyError, TypeError):
        return
    doc = h.text(h.spec_doc).replace("**", "").replace("−", "-")
    for row in h.spec:
        v = card.get(row.key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v:
            continue
        written = [f.format(v) for f in QUOTE_FORMATS]
        written += [f.format(v) for f in QUOTE_FIXED] if abs(v) >= 1 else []
        named = _row_lines(doc, row)
        if not named:
            L.fail("spec-quotes",
                   f"no line of {h.spec_doc} names {row.id or row.key} — certified "
                   f"{row.key} = {v:.4g} cannot be matched against its own row",
                   f"give the row an `id:` in harness.yaml and write that id (or the key "
                   f"`{row.key}`, or the label `{row.label}`) in its line of {h.spec_doc}")
            continue
        # ONLY the row's own line(s): a document-wide set of numbers passes any certified value
        # that coincides with any number anywhere in the file — a bound, a sample count, a date.
        # And whole tokens, never a substring: `62` inside `1620` is not a quotation of 62, and a
        # doc that says `62` is not quoting a certified 62.4.
        tokens = {t for ln in named for t in NUMBER.findall(ln)}
        if not tokens.intersection(written):
            L.fail("spec-quotes",
                   f"certified {row.key} = {v:.4g} is not quoted in the {row.id or row.key} row of {h.spec_doc}",
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
    import subprocess  # noqa: PLC0415 - local: a design's lint.py may not import it at module level

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



# How many of the biggest run dirs `scratch_budget` names in its warning. Enough to point at the
# campaign that filled the disk, few enough that the warning stays one screen.
BIGGEST = 5


def scratch_budget(L: Lint) -> None:
    """SOFT: this checkout's work dir is over the warn threshold, and its biggest runs are unreduced.

    Never a failure, on purpose (template#37). Scratch is not an invariant of the design — it is a
    property of the machine the design happens to be running on, and a gate that goes red because
    an overnight campaign is still in flight is a gate people switch off. But 212 GB of transient
    records, every one already reduced to a committed table, accumulated in one account's scratch
    because nothing ever said so out loud; a warning at lint time is the cheapest place to say it.

    What it reports is the pair, not the size alone: a work dir over `$SX_SCRATCH_WARN_GB` (50 GB
    by default) whose largest run dirs have no reduction row in the ledger. That is the shape that
    means work is being lost as well as disk — a raw record nobody has reduced is a re-simulation
    waiting to happen, not evidence.
    """
    from scripts import clean_runs  # noqa: PLC0415 - local: only this check pays for the import

    work, _note = clean_runs.work_dir()
    if work is None or not work.is_dir():
        return                      # nothing has simulated in this checkout: nothing to report
    rep = clean_runs.usage(work)
    if not rep["over"]:
        return
    entries = clean_runs.scan(work / "runs", clean_runs.rows_by_label(L.rows()))
    biggest = sorted(entries, key=lambda e: -e["bytes"])[:BIGGEST]
    unreduced = [e for e in biggest if not e["reduced"]]
    where = f"{rep['work']} holds {rep['human']} in {rep['runs']} run dir(s), over the "\
            f"{rep['warn_gb']:g} GB mark (${clean_runs.WARN_GB_ENV})"
    if unreduced:
        names = ", ".join(f"{e['name']} ({clean_runs.human_bytes(e['bytes'])})" for e in unreduced)
        L.warn("scratch-budget",
               f"{where}, and {len(unreduced)} of its {len(biggest)} biggest run dir(s) have no "
               f"reduction row: {names}",
               "reduce each one to the number it was run for, commit that reduction (a scorecard, "
               "an experiment table, a ledger row), then `make clean-runs` — a raw simulation "
               "record is scratch, not evidence, and the deck rebuilds it")
    else:
        L.warn("scratch-budget",
               f"{where}; every one of its {len(biggest)} biggest run dir(s) is already reduced",
               "`make clean-runs` (it keeps anything unreduced, running, or younger than AGE); "
               "`make clean-runs AGE=0` once the campaign is finished")

# `package-importable` is NOT here: the platform ships it (driven by `package:` in harness.yaml).
EXTRA = (deck_rebuild, deck_portable, deck_models, spec_quotes, sx_links,
         artifact_home, signoff_index, scratch_budget)


def hook_info(repo: Path = REPO) -> str:
    """One INFO line: is the opt-in pre-push guard hook installed in this checkout?

    Deliberately NOT a check in `EXTRA`, and deliberately not `L.warn` either. `fail` would make
    a per-clone convenience block the repo; `warn` does not block, but the run still ends with
    "all invariants hold (… hook …)", and hook installation is not an invariant of this design —
    it is a choice its owner makes per checkout, on a repo whose standing stance is that a hook
    which blocks ordinary work gets removed. So it prints, the invariant list is untouched, and
    the exit code never depends on it.
    """
    try:
        where = githook.state(repo)
    except SystemExit:
        return "INFO: not a git checkout, so there is no pre-push guard hook to report on"
    if where == "ours":
        return "INFO: pre-push guard hook installed — `make guard` runs before every push"
    if where == "foreign":
        return (f"INFO: {githook.hook_path(repo)} exists but is not the guard hook — "
                f"left alone; `make guard` before pushing, by hand")
    return "INFO: pre-push guard hook not installed — `make hook-install` (optional, per clone)"


if __name__ == "__main__":
    rc = lint.main(load(REPO), extra=EXTRA)
    print(hook_info())
    sys.exit(rc)
