"""The `memory:` block of `harness.yaml`: the pack budget, the archive dir and the fleet index.

`make template-update` does not carry `harness.yaml` into a design, while it does carry this file.
So the first test pins the template's own values and runs only on the bare template, and the pack
tests read whatever this checkout's `harness.yaml` declares, skipping a key it does not declare.

The pack is built on a copy of this checkout placed as the design directory places a clone
(`<directory>/designs/<name>/`), so a relative `fleet_index` of `../../registry/…` resolves inside
the test's own directory.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _h(root: Path = REPO):
    from spicexplorer_harness import load

    return load(root)


def test_the_template_declares_a_budget_an_archive_and_a_fleet_index():
    h = _h()
    if h.name != "<design>":
        pytest.skip(f"harness.yaml is this design's own (name: {h.name}): the template's values "
                    "are not asserted on it")
    assert h.memory_pack_budget == 20000
    assert h.archived_dirs == ["doc/memory/archive"]
    assert h.memory_fleet_index == "../../registry/fleet-lessons.json"
    # the index is held to the entry cap in live rows; no separate, larger index cap
    assert h.memory_index_size_cap == 0
    assert (REPO / "doc" / "memory" / "archive" / "README.md").is_file()


def _entry(i: int, word: str = "") -> str:
    body = f"line {i} of a lesson about the compensation network {word} " * 6
    return (f"# 2026-09-{1 + i % 28:02d} — lesson {i:03d}\n\n"
            f"KIND: journal entry | type: semantic | status: live\n\n{body.strip()}\n")


@pytest.fixture
def placed(tmp_path: Path) -> Path:
    """A copy of this checkout's harness.yaml, doc/ and references/ at designs/probe/."""
    root = tmp_path / "designs" / "probe"
    root.mkdir(parents=True)
    shutil.copy(REPO / "harness.yaml", root / "harness.yaml")
    for d in ("doc", "references"):
        if (REPO / d).is_dir():
            shutil.copytree(REPO / d, root / d)
    return root


def _pack(root: Path) -> str:
    from spicexplorer_harness import context_pack as CP

    h = _h(root)
    return CP.render(h, CP.build(h, []))


def test_the_pack_says_what_the_budget_dropped_and_skips_the_archive(placed):
    h = _h(placed)
    if not h.memory_pack_budget:
        pytest.skip("harness.yaml declares no memory.pack_budget (template v2.14 sets 20000)")
    loaded = placed / h.load_dirs[0]
    loaded.mkdir(parents=True, exist_ok=True)
    for i in range(h.memory_pack_budget // 100):        # about 2.5x the budget in lesson lines
        (loaded / f"lesson-{i:04d}.md").write_text(_entry(i))
    for rel in h.archived_dirs:
        (placed / rel).mkdir(parents=True, exist_ok=True)
        (placed / rel / "archived-lesson.md").write_text(_entry(9999, "quarantinedword"))
    text = _pack(placed)
    heading = next(ln for ln in text.splitlines() if ln.startswith("## Lessons"))
    assert f"dropped, budget {h.memory_pack_budget // 1000} kB" in heading, heading
    assert "quarantinedword" not in text and "archived-lesson" not in text


def test_the_pack_reads_the_fleet_index_beside_a_placed_clone(placed):
    h = _h(placed)
    if not h.memory_fleet_index or Path(h.memory_fleet_index).is_absolute():
        pytest.skip("harness.yaml declares no relative memory.fleet_index (template v2.14 sets "
                    "../../registry/fleet-lessons.json)")
    assert "## Fleet lessons" not in _pack(placed)       # no index file yet: no section
    index = (placed / h.memory_fleet_index).resolve()
    assert placed.parents[1] in index.parents, index     # the test writes only in its own dir
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({
        "version": 1, "generated_at": "2026-09-20", "commits": {},
        "entries": [{"design": "another-design", "file": "doc/journal/tail-current.md",
                     "title": "2026-09-19 — tail current sets the slew rate",
                     "hook": "tail current sets the slew rate", "type": "semantic",
                     "date": "2026-09-19", "pdk": "", "scope": "design", "summary": "",
                     "keys": []}],
    }))
    text = _pack(placed)
    assert "## Fleet lessons" in text
    assert "tail current sets the slew rate" in text
