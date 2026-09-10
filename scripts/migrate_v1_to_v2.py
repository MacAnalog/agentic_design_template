#!/usr/bin/env python3
"""Template 1.xx -> 2.00: give every artefact a home.

`make template-update` refuses to cross a MAJOR release, because 2.00 MOVES directories and a
three-way merge cannot move a file. This script does the moving. It is deliberate, it is run once
per design, and it commits nothing — you read `git status`, run the gates, then commit.

What 2.00 changes, and what this script does about it:

| change | what happens here |
|---|---|
| `pdf/` -> `references/` | `git mv`, then every `pdf/INDEX.md` mention in the tree is repointed |
| the design of record moves into `signoff/` | the tree is created; a single frozen `decks/<ref>` is moved into `signoff/prelayout/decks` and `harness.yaml` repointed |
| layout artefacts leave the code directory | `layout/*.gds|*.png|drc*|lvs*|*.pex.sp` -> `signoff/layout/` |
| experiments name their phase | `**Phase:** <unset>` is inserted in every experiment README, and `Phase` added to `experiments_rows` |
| the package stops shimming stimulus/eye | NOTHING is deleted: a design that imports `<pkg>.eye` keeps its own copy and is told so |

    scripts/migrate_v1_to_v2.py --dry-run     # say what would move, touch nothing
    scripts/migrate_v1_to_v2.py               # do it; then `make lint && make test && make check`
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO / ".sx" / "template-version"
TARGET = "2.00"
FIDELITIES = ("prelayout", "postlayout-pex", "postlayout-em")
TEXT_SUFFIXES = (".md", ".py", ".yaml", ".yml", ".txt", ".ipynb")


def sh(*args: str, check: bool = True) -> str:
    r = subprocess.run(args, cwd=REPO, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"$ {' '.join(args)}\n{r.stdout}{r.stderr}")
    return r.stdout


class Plan:
    """Every action is recorded before it is taken, so `--dry-run` and the real run agree."""

    def __init__(self, dry: bool) -> None:
        self.dry, self.rows = dry, []

    def do(self, what: str, fn) -> None:
        self.rows.append(what)
        if not self.dry:
            fn()

    def note(self, what: str) -> None:
        self.rows.append(f"(no change) {what}")


def package() -> str:
    for line in (REPO / "harness.yaml").read_text().splitlines():
        if line.startswith("package:"):
            return line.split(":", 1)[1].split("#")[0].strip()
    return "design"


def require_harness() -> None:
    """This migration only knows how to move a repo the harness describes.

    Two of the lab's designs predate the template and carry no `harness.yaml`: they hand-roll
    their own context pack and lint, with the caps written into the scripts. Every step below —
    the package name, `papers_dir`, `frozen`, `experiments_rows` — reads that file, so on such a
    repo this script would move directories and then fail partway with a bare FileNotFoundError.
    Refuse first, and say what the alternative is.
    """
    if (REPO / "harness.yaml").is_file():
        return
    raise SystemExit(
        f"{REPO.name} has no harness.yaml, so it was never cut from this template and this "
        f"migration does not apply to it.\n"
        f"    FIX: nothing here is urgent — a repo outside the harness contract stays outside it. "
        f"To bring it in, adopt the template first (write harness.yaml, `.sx/template-version`, "
        f"and the package layout) and then run migrations normally. Moving its directories "
        f"without that leaves it neither shape.")


def tracked_text_files() -> list[Path]:
    """Tracked text files, each once.

    `git ls-files` lists an UNMERGED path once per stage, and by the time this runs the three-way
    merge above has left conflicts — so without the dedupe every conflicted file is reported (and
    rewritten) three times.
    """
    out: dict[str, Path] = {}
    for rel in sh("git", "ls-files", "-z").split("\0"):
        p = REPO / rel
        if rel and rel.endswith(TEXT_SUFFIXES) and not p.is_symlink() and p.is_file():
            out[rel] = p
    return list(out.values())


def rename_papers(plan: Plan) -> None:
    old, new = REPO / "pdf", REPO / "references"
    if new.is_dir() and not old.is_dir():
        plan.note("references/ already exists")
    elif old.is_dir():
        plan.do("git mv pdf references", lambda: sh("git", "mv", "pdf", "references"))
    else:
        plan.do("mkdir references (no pdf/ to move)", lambda: new.mkdir(exist_ok=True))

    me = Path(__file__).resolve()
    y = REPO / "harness.yaml"
    text = y.read_text()
    if "papers_dir" not in text:
        plan.do("harness.yaml: papers_dir/papers_index -> references/",
                lambda: y.write_text(text.replace(
                    "\nfrozen:", "\npapers_dir: references\npapers_index: references/INDEX.md\n\nfrozen:", 1)))
    elif "pdf" in text.split("papers_dir")[1].split("\n")[0]:
        plan.do("harness.yaml: papers_dir/papers_index pdf -> references",
                lambda: y.write_text(text.replace("papers_dir: pdf", "papers_dir: references")
                                         .replace("papers_index: pdf/", "papers_index: references/")))

    hits = [p for p in tracked_text_files()
            if p.resolve() != me and "pdf/INDEX.md" in p.read_text(errors="ignore")]
    for p in hits:
        rel = p.relative_to(REPO).as_posix()
        plan.do(f"repoint pdf/INDEX.md -> references/INDEX.md in {rel}",
                lambda p=p: p.write_text(p.read_text().replace("pdf/INDEX.md", "references/INDEX.md")))


REMOTE = "template"
URL = "https://github.com/MacAnalog/agentic_design_template.git"


def have_target(template: Path | None) -> bool:
    """Is template v2.00 reachable? Nothing may move until it is.

    A half-migration is the worst outcome: directories moved, the templates and the content
    changes missing, and `.sx/template-version` claiming 2.00. So this is checked before the first
    file moves, not discovered in the middle.
    """
    if template is not None:
        return (template / "signoff" / "README.md").is_file()
    if REMOTE not in sh("git", "remote").split():
        sh("git", "remote", "add", REMOTE, URL)
    # --force: a design that fetched an earlier v2.00 (a moved tag, a retagged release) would
    # otherwise fail with "would clobber existing tag" and take the migration down with it.
    sh("git", "fetch", "--quiet", "--tags", "--force", REMOTE, check=False)
    return bool(sh("git", "tag", "--list", f"v{TARGET}").strip())


def template_file(rel: str) -> str | None:
    """`signoff/<rel>` as the v2.00 tag holds it, fetched from the template remote.

    The same remote `template_update.py` uses. A design that has never fetched it gets it here, so
    the migration needs no second checkout on disk and no `--template` flag.
    """
    if REMOTE not in sh("git", "remote").split():
        sh("git", "remote", "add", REMOTE, URL)
    out = sh("git", "show", f"v{TARGET}:signoff/{rel}", check=False)
    return out or None


def make_signoff(plan: Plan, template: Path | None) -> None:
    root = REPO / "signoff"
    for sub in ("schematic", "layout", *[f"{f}/{d}" for f in FIDELITIES for d in ("figs", "tables")]):
        d = root / sub
        if d.is_dir():
            continue
        # `.gitkeep`, not a bare mkdir: git does not track an empty directory, so a plain mkdir
        # produces a tree that `signoff/README.md` describes and the repo does not actually have.
        # Measured on two migrated designs, which ended up with no `figs/` or `tables/` at all.
        keep = d / ".gitkeep"
        plan.do(f"mkdir signoff/{sub} (+ .gitkeep, so git keeps it)",
                lambda d=d, k=keep: (d.mkdir(parents=True, exist_ok=True), k.touch()))
    for rel in ["README.md", "schematic/README.md", "layout/README.md",
                *[f"{f}/REPORT.md" for f in FIDELITIES]]:
        dst = root / rel
        if dst.exists():
            plan.note(f"signoff/{rel} already exists")
            continue
        src = (template / "signoff" / rel) if template else None
        body = src.read_text() if (src and src.is_file()) else template_file(rel)
        if body is None:
            plan.note(f"signoff/{rel} could not be fetched from the template — copy it by hand "
                      f"from a v{TARGET} checkout")
        else:
            plan.do(f"write signoff/{rel} from template v{TARGET}",
                    lambda d=dst, b=body: (d.parent.mkdir(parents=True, exist_ok=True), d.write_text(b)))


PROV_PATH_KEYS = ("script", "raw")


def _frozen_entries() -> tuple[list[str], str]:
    y = (REPO / "harness.yaml").read_text()
    # re.S on purpose: a real design wraps the list over two lines, and a single-line regex
    # reports "nothing is frozen" for a repo with six frozen dirs.
    m = re.search(r"^frozen:\s*\[(.*?)\]", y, re.M | re.S)
    entries = [e.strip().strip("'\"") for e in m.group(1).split(",") if e.strip()] if m else []
    c = re.search(r'^reference_scorecard:\s*["\']?([^"\'\n#]*)', y, re.M)
    return entries, (c.group(1).strip() if c else "")


def _relocatable(src: str) -> tuple[bool, list[str], str]:
    """Can `src` move, and which provenance path fields would have to follow it?

    A scorecard's `provenance` block records `script` and `raw` as REPO-RELATIVE paths, each
    beside a sha of that file's CONTENTS. So a path pointing inside the directory being moved
    stops resolving — that is the breakage measured on a live design (`scorecard-recompute`:
    "raw <path> is missing"). It is also the whole of the breakage: rewriting the pointer keeps
    every hash valid, because no byte of the rawfile, the scorer or any number changes.

    Returns (movable, keys-to-rewrite, why-not).
    """
    card = REPO / src / "scorecard.json"
    if not card.is_file():
        return True, [], ""
    try:
        prov = json.loads(card.read_text()).get("provenance")
    except ValueError as exc:
        return False, [], f"{src}/scorecard.json is not JSON ({exc})"
    if not isinstance(prov, dict) or not prov:
        return True, [], ""            # a scorecard with no provenance block records no paths
    keys = [k for k in PROV_PATH_KEYS
            if (prov.get(k) or "").startswith(src.rstrip("/") + "/")]
    return True, keys, ""


def relocate(plan: Plan, src: str, dst: str) -> None:
    """Move one frozen dir to `dst`, carrying its provenance pointers with it."""
    movable, keys, why = _relocatable(src)
    if not movable:
        plan.note(f"{src} NOT moved: {why}")
        return
    (REPO / dst).parent.mkdir(parents=True, exist_ok=True)
    plan.do(f"git mv {src} {dst}", lambda: sh("git", "mv", src, dst))
    if keys:
        def rewrite(src=src, dst=dst, keys=keys):
            f = REPO / dst / "scorecard.json"
            doc = json.loads(f.read_text())
            for k in keys:
                doc["provenance"][k] = doc["provenance"][k].replace(src.rstrip("/") + "/",
                                                                    dst.rstrip("/") + "/", 1)
            f.write_text(json.dumps(doc, indent=1) + "\n")
        plan.do(f"{dst}/scorecard.json: repoint provenance {'+'.join(keys)} at the new path "
                f"(the sha of each file's CONTENTS is unchanged, so every hash still re-derives)",
                rewrite)
    y = REPO / "harness.yaml"
    plan.do(f"harness.yaml: frozen/reference_scorecard {src} -> {dst}",
            lambda: y.write_text(y.read_text().replace(src.rstrip("/"), dst.rstrip("/"))))


def move_reference(plan: Plan, record: str | None) -> None:
    """Move the design of record into `signoff/prelayout/decks` — when told which one it is.

    Two things are deliberately NOT inferred:

    * **Which frozen dir is the design of record.** `reference_scorecard` cannot tell you: it means
      "the scorecard `make check` reproduces", which a design may legitimately point at a prior-art
      YARDSTICK it is trying to beat. Measured on live designs: one had `reference` as the yardstick
      and `candidate` as the result; another had six frozen dirs of which two were a control and a
      reference. So it is an argument, `--design-of-record`, not a guess.
    * **Whether to move a yardstick or a control.** They stay in `decks/`, which is a declared
      artefact home. `signoff/` is for this design's own results.
    """
    entries, card = _frozen_entries()
    if not entries:
        plan.note("nothing is frozen yet — certify straight into signoff/prelayout/decks when you "
                  "do, and the provenance block names the right path from the start")
        return
    if not record:
        plan.note(
            f"frozen: {entries} — not moved, because nothing here says which is THIS DESIGN'S "
            f"result.\n"
            f"      Re-run with `--design-of-record <dir>` and it moves, provenance and all. Do "
            f"not let `reference_scorecard: {card or '(unset)'}` decide: that key means 'the "
            f"scorecard `make check` reproduces', which may legitimately be a prior-art yardstick.\n"
            f"      A yardstick, a control or a withdrawn row STAYS in `decks/` — `signoff/` is "
            f"for this design's own results. Name each one's role in signoff/README.md.")
        return
    record = record.rstrip("/")
    if record not in entries:
        raise SystemExit(f"--design-of-record {record!r} is not in frozen: {entries}")
    if record.startswith("signoff/"):
        plan.note(f"{record} already lives under signoff/")
        return
    relocate(plan, record, "signoff/prelayout/decks")
    # The ledger records the same paths, and it is NOT rewritten: "never hand-edit the ledger —
    # an edited row is not evidence of a run" (doc/memory/README.md). A row naming the old path is
    # a true record of where the file was when that run happened.
    led = REPO / "runs" / "ledger.ndjson"
    if led.is_file() and record.rstrip("/") in led.read_text(errors="replace"):
        plan.note(
            f"runs/ledger.ndjson has rows naming {record} — LEFT ALONE, deliberately. They are "
            f"true records of where the file was at the time, and an edited row is not evidence "
            f"of a run.\n"
            f"      Consequence: `scorecard-recompute` reports 'raw {record}/decks.sha256 is "
            f"missing' for those rows IN THIS CHECKOUT. The ledger is git-ignored and per "
            f"checkout, so a fresh clone never sees it. It clears at the next certification, which "
            f"logs a row at the new path.")

    rest = [e for e in entries if e != record]
    if rest:
        plan.note(f"left in place (not this design's result): {rest} — give each a role row in "
                  f"signoff/README.md")


def move_layout_artifacts(plan: Plan) -> None:
    d = REPO / "layout"
    if not d.is_dir():
        return
    pats = ("*.gds", "*.gds.gz", "*.png", "*.svg", "drc*.txt", "lvs*.txt", "*.pex.sp", "params.json")
    for pat in pats:
        for p in sorted(d.glob(pat)):
            rel = p.relative_to(REPO).as_posix()
            plan.do(f"git mv {rel} signoff/layout/{p.name}",
                    lambda rel=rel, p=p: sh("git", "mv", rel, f"signoff/layout/{p.name}"))


def phase_rows(plan: Plan) -> None:
    y = REPO / "harness.yaml"
    text = y.read_text()
    if "experiments_rows" not in text:
        plan.do("harness.yaml: experiments_rows: [Phase, Paper, Hypothesis, Verdict]",
                lambda: y.write_text(text.replace(
                    "\nfrozen:", "\nexperiments_rows: [Phase, Paper, Hypothesis, Verdict]\n\nfrozen:", 1)))
    elif "Phase" not in text.split("experiments_rows")[1].split("\n")[0]:
        plan.do("harness.yaml: add Phase to experiments_rows", lambda: y.write_text(
            re.sub(r"^experiments_rows:\s*\[", "experiments_rows: [Phase, ", text, flags=re.M)))

    for readme in sorted((REPO / "experiments").glob("*/README.md")):
        if readme.parent.name == "_template":
            continue
        t = readme.read_text()
        if "**Phase" in t:
            continue
        rel = readme.relative_to(REPO).as_posix()
        # Two README shapes are in the wild and both satisfy the harness check (it looks for the
        # substring `**Phase`): bold lines (`**Paper(s):** …`) and two-column tables
        # (`| **Paper(s)** | … |`). Match whichever this file uses, or the row is inserted in a
        # form its own table will not render — and `make lint` fails on a file the migration
        # claims to have fixed.
        m = re.search(r"^(\|\s*)?\*\*Paper", t, re.M)
        if not m:
            plan.note(f"{rel}: no **Paper row to anchor **Phase** to — add it by hand")
            continue
        row = ("| **Phase** | <unset — system \\| topology \\| sizing \\| improve \\| layout> |\n"
               if m.group(1) else
               "**Phase:** <unset — system | topology | sizing | improve | layout>\n")
        plan.do(f"insert a **Phase** row in {rel} ({'table' if m.group(1) else 'bold-line'} form)",
                lambda p=readme, t=t, i=m.start(): p.write_text(t[:i] + row + t[i:]))


SUFFIXES = (".png", ".svg", ".pdf", ".csv", ".gds", ".gds.gz")
HOMES = ("signoff/", "experiments/", "layout/", "decks/", "references/", "doc/", "notebooks/",
         ".claude/", ".sx/", ".github/", "pdf/")


def artifact_survey(plan: Plan) -> None:
    """Count what 2.00's new `artifact-home` check would flag, and where.

    Not a failure and not fixed here: a design's own durable output directory is a legitimate
    home, it just has to be DECLARED. This says how many files and which directories, so the
    owner can move them or add the line — before `make lint` says it in a less useful order.
    """
    out: dict[str, int] = {}
    for rel in sh("git", "ls-files", "-z").split("\0"):
        if rel and rel.endswith(SUFFIXES) and not rel.startswith(HOMES):
            out[rel.split("/")[0]] = out.get(rel.split("/")[0], 0) + 1
    if not out:
        plan.note("artifact-home: nothing to declare — every committed artefact already has a home")
        return
    where = ", ".join(f"{d}/ ({n})" for d, n in sorted(out.items(), key=lambda kv: -kv[1]))
    plan.note(f"artifact-home would flag {sum(out.values())} committed artefact(s) in: {where}. "
              f"Move them, or add each directory to ARTIFACT_HOMES in scripts/lint.py with one "
              f"line saying what lives there")


def shim_warning(plan: Plan) -> None:
    pkg = package()
    for mod in ("eye", "stimulus"):
        if (REPO / pkg / f"{mod}.py").is_file():
            plan.note(f"{pkg}/{mod}.py stays: 2.00 stopped SHIPPING it in the template, and deletes "
                      f"nothing here. To drop it, import spicexplorer_waveview.{mod} directly")


def propagate(plan: Plan, cur: str) -> list[tuple[str, str, str]]:
    """After the moves, take 2.00's CONTENT changes the ordinary way: a three-way merge, file by file.

    The moves above are what a merge cannot do; everything else in 2.00 is an ordinary diff — the
    two new lint checks, `exp.csv`, the package docstring, the README and CLAUDE.md sections. So
    this reuses `template_update._apply` rather than reimplementing it, excluding by hand exactly
    what the moves already handled, plus the two shims 2.00 stopped shipping (they are DELETED in
    the template's diff, and deleting a design's working module is not this script's business).
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import template_update as tu  # noqa: PLC0415
    except ModuleNotFoundError:
        raise SystemExit(
            "scripts/template_update.py is missing, so there is no way to take 2.00's content "
            "changes — and this repo was therefore never wired to the template's release "
            "machinery at all.\n"
            "    FIX: if this design IS template-derived, restore the file "
            "(`git fetch --tags --force template && git show v2.00:scripts/template_update.py > "
            "scripts/template_update.py`) and record the release it was cut from in "
            "`.sx/template-version`, then re-run. If it predates the template, it is outside the "
            "contract and this migration does not apply — adopt the template deliberately first."
        ) from None

    if not hasattr(tu, "_apply"):
        raise SystemExit(
            "this design's scripts/template_update.py predates 1.04, which is where the file-by-file "
            "three-way apply this migration reuses was added.\n"
            "    FIX: `make template-update` first (it will take you to the newest 1.xx), then re-run "
            "this script. Crossing 1.00 -> 2.00 in one step would apply the whole patch atomically, "
            "and one missing file would silently roll back every file that had merged.")
    # `have_target` already fetched, with --force; tu.fetch() would repeat it without.
    tags = [x[1:] for x in sh("git", "tag", "--list", "v*").split() if tu.VER_RE.match(x[1:])]
    if TARGET not in tags:
        plan.note(f"template v{TARGET} is not among the release tags {tags}: content changes not "
                  f"propagated. Fetch the template remote and re-run.")
        return []
    if plan.dry:
        plan.note(f"would three-way merge the content changes of {cur} -> {TARGET}")
        return []
    pkg_exclude = [*tu.PKG_EXCLUDE, ":!eye.py", ":!stimulus.py"]
    exclude = [*tu.EXCLUDE, ":!pdf", ":!references", ":!signoff", ":!.sx/template-version",
               ":!scripts/migrate_v1_to_v2.py"]  # never let the running script rewrite itself
    rows = tu._apply(cur, TARGET, ["design/", *pkg_exclude], directory=package(), relative="design/")
    rows += tu._apply(cur, TARGET, [".", ":!design", *exclude])
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="migrate_v1_to_v2")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--design-of-record", metavar="DIR", help="the frozen dir holding THIS "
                    "design's own certified benches; it moves to signoff/prelayout/decks. Never "
                    "inferred — a yardstick and a control are frozen too")
    ap.add_argument("--template", type=Path, help="a local checkout of agentic_design_template at "
                                                  "v2.00. Optional: without it the templates come "
                                                  "from the `template` git remote's v2.00 tag")
    a = ap.parse_args(argv)

    if not a.dry_run and sh("git", "status", "--porcelain").strip():
        raise SystemExit("the worktree is dirty. This migration MOVES files — commit or stash "
                         "first, so `git status` afterwards shows only what it did.")
    require_harness()
    cur = VERSION_FILE.read_text().strip() if VERSION_FILE.is_file() else "(unrecorded)"
    print(f"template {cur} -> {TARGET}   package: {package()}\n")
    if not have_target(a.template):
        raise SystemExit(
            f"template v{TARGET} is not reachable, so this migration would move directories and "
            f"then have nothing to fill them with.\n"
            f"    FIX: `git fetch --tags {REMOTE}` (the remote is added automatically; it is "
            f"{URL}), or pass --template <a v{TARGET} checkout>.")

    plan = Plan(a.dry_run)
    # Content FIRST, on a clean tree: `git apply --3way` reads the index for its preimage, so a
    # file this script has already edited is rejected ("does not match index"). Then the moves.
    rows = propagate(plan, cur if cur != "(unrecorded)" else "1.00")
    rename_papers(plan)
    make_signoff(plan, a.template)
    move_reference(plan, a.design_of_record)
    move_layout_artifacts(plan)
    phase_rows(plan)
    artifact_survey(plan)
    shim_warning(plan)
    if rows:
        print("  content changes (three-way merge, file by file):")
        width = max(len(r[0]) for r in rows)
        for name, verdict, msg in rows:
            print(f"    {name:<{width}}  {verdict}")
            if msg:
                print("        " + msg.replace("\n", "\n        "))
        print()
    for row in plan.rows:
        print(f"  {row}")

    if a.dry_run:
        print("\n--dry-run: nothing changed. Re-run without it to apply.")
        return 0
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(TARGET + "\n")
    print(f"\n.sx/template-version -> {TARGET} (nothing is committed)")
    print("NOW, in this order:")
    print("  1. `make lint`   — `artifact-home` and `signoff-index` are new; both carry their fix")
    print("  2. `make test`")
    print("  3. `make check`  — the reference moved, so prove it still reproduces its scorecard")
    print("  4. resolve every CONFLICT above — they are decisions: 2.00's generic change meeting")
    print("     your design's own lines (`scripts/lint.py` is the usual one)")
    print("  5. fill each experiment's `**Phase:**`, and `signoff/README.md`'s table")
    print("  6. read `git status`, then commit")
    return 1 if any(r[1] in ("CONFLICT", "REJECTED") for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
