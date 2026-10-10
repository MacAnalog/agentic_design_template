"""The committed skill links match the pinned library, and CLAUDE.md points at the checkpoint skill.

`.claude/skills/` holds one committed symlink per skill in the library's `design` link set
(`.sx/skills/linksets/design.txt`). A pin bump that adds a skill to that set without the link
leaves a fresh clone without the skill until someone runs `make init`.

On `lane: bridge` the incremental upload of a design's cellviews to its OA library (five
checkpoints, the designer reviewing in parallel with the agents) is written in one library skill,
the `*-checkpoints` link. CLAUDE.md points at it by that pattern and does not restate it. The
skill's full name stays out of this file and out of CLAUDE.md, because the open lane's `denylist:`
scans both.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / ".claude" / "skills"
LIBRARY = REPO / ".sx" / "skills"


def _committed_skill_links(repo: Path = REPO) -> set[str]:
    """Names of the symlinks committed under `.claude/skills/` (git mode 120000)."""
    r = subprocess.run(
        ["git", "ls-files", "-s", "--", ".claude/skills"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode:
        pytest.skip("not a git checkout")
    names = set()
    for line in r.stdout.splitlines():
        meta, path = line.split("\t", 1)
        if meta.split()[0] == "120000" and path.count("/") == 2:
            names.add(path.rsplit("/", 1)[1])
    return names


def _library_initialised() -> bool:
    return (LIBRARY / "bin" / "sx-link").is_file()


def _lanes_section() -> str:
    text = (REPO / "CLAUDE.md").read_text()
    m = re.search(r"^## Simulation lanes.*?(?=^## )", text, flags=re.MULTILINE | re.DOTALL)
    assert m, "CLAUDE.md has no '## Simulation lanes' section"
    return m.group(0)


def test_one_checkpoint_skill_link_is_committed():
    found = sorted(n for n in _committed_skill_links() if n.endswith("-checkpoints"))
    assert len(found) == 1, f"expected one committed .claude/skills/*-checkpoints link, got {found}"


def test_the_checkpoint_skill_link_resolves_to_its_skill():
    if not _library_initialised():
        pytest.skip(".sx/skills is not initialised (make init)")
    links = sorted(SKILLS.glob("*-checkpoints"))
    assert len(links) == 1, links
    skill = links[0] / "SKILL.md"
    assert skill.is_file(), f"{links[0]} does not resolve into the pinned .sx/skills"
    m = re.search(r"^name:\s*(\S+)", skill.read_text(), flags=re.MULTILINE)
    assert m and m.group(1) == links[0].name, (m and m.group(1), links[0].name)


def test_claude_md_points_at_the_checkpoint_skill_in_the_lanes_section():
    section = _lanes_section()
    assert "`*-checkpoints`" in section, "the lanes section does not point at the checkpoint skill"


def _design_link_set() -> set[str]:
    lines = (LIBRARY / "linksets" / "design.txt").read_text().splitlines()
    return {
        s.split("/", 1)[1]
        for s in (x.split("#", 1)[0].strip() for x in lines)
        if s.startswith("skills/")
    }


def _missing_design_links(repo: Path = REPO) -> set[str]:
    """Skills of the pinned `design` link set with no committed link in `repo`.

    A subset check, not equality: a design that declares `pdk:` commits the library's `pdk-<id>`
    link (`make skills-update` stages `.claude`), and a design may commit its own skill links.
    """
    return _design_link_set() - _committed_skill_links(repo)


def test_every_pinned_design_skill_has_a_committed_link():
    if not _library_initialised():
        pytest.skip(".sx/skills is not initialised (make init)")
    assert not _missing_design_links()


def test_a_committed_pdk_link_in_a_design_passes_the_link_check(tmp_path: Path):
    """A design that declares `pdk:` commits the `pdk-<id>` link beside the design set."""
    if not _library_initialised():
        pytest.skip(".sx/skills is not initialised (make init)")
    pdk_sets = sorted((LIBRARY / "linksets").glob("pdk-*.txt"))
    if not pdk_sets:
        pytest.skip("the pinned library has no pdk-<id> link set")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    skills = tmp_path / ".claude" / "skills"
    skills.mkdir(parents=True)
    for name in sorted(_design_link_set() | {pdk_sets[0].stem}):
        (skills / name).symlink_to(f"../../.sx/skills/skills/{name}")
    subprocess.run(["git", "add", ".claude"], cwd=tmp_path, check=True)
    assert pdk_sets[0].stem in _committed_skill_links(tmp_path)
    assert not _missing_design_links(tmp_path)
