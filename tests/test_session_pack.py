"""The SessionStart hook (`scripts/session_pack.py`, wired in `.claude/settings.json`).

It must exit 0 and print nothing when there is no venv, no harness.yaml, or a pack that fails or
hangs; otherwise it prints the pack in at most `memory.pack_budget` bytes. The venv interpreter
is a stand-in: a shell script at `<root>/.venv/bin/python`, either a stub or one that runs this
test's own interpreter (a symlink would lose the venv's site-packages).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "session_pack.py"


def _mod():
    spec = importlib.util.spec_from_file_location("session_pack_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _checkout(tmp_path: Path, *, harness: bool = True, python: str | None = None) -> Path:
    """A checkout: the hook script, optionally a harness.yaml (with doc/, references/) and a
    `.venv/bin/python` whose body is `python` (a shell script)."""
    root = tmp_path / "co"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "session_pack.py")
    if harness:
        shutil.copy(REPO / "harness.yaml", root / "harness.yaml")
        for d in ("doc", "references"):
            if (REPO / d).is_dir():
                shutil.copytree(REPO / d, root / d)
    if python is not None:
        py = root / ".venv" / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.write_text(f"#!/bin/sh\n{python}\n")
        py.chmod(0o755)
    return root


def _hook(root: Path) -> subprocess.CompletedProcess:
    """The script as the hook runs it: the system python3, stdout captured."""
    return subprocess.run(["python3", str(root / "scripts" / "session_pack.py")], cwd=root,
                          capture_output=True, text=True, timeout=60, check=False)


def test_silent_without_a_venv(tmp_path):
    r = _hook(_checkout(tmp_path))
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_silent_without_a_harness_yaml(tmp_path):
    r = _hook(_checkout(tmp_path, harness=False, python=f'exec "{sys.executable}" "$@"'))
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_silent_when_the_pack_fails(tmp_path):
    r = _hook(_checkout(tmp_path, python='echo "Traceback: boom" >&2; exit 1'))
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_silent_when_the_pack_hangs(tmp_path):
    root = _checkout(tmp_path, python="exec sleep 30")
    assert _mod().pack(root, timeout=0.5) == ""


def test_a_long_pack_is_cut_to_the_budget_and_says_so(tmp_path):
    line = "- a lesson line of sixty-odd bytes, repeated past the budget"
    root = _checkout(tmp_path, python=f"echo 2000; for i in $(seq 200); do echo '{line}'; done")
    r = _hook(root)
    assert r.returncode == 0
    assert len(r.stdout.encode()) <= 2000
    assert r.stdout.startswith("- a lesson line") and "cut here at memory.pack_budget" in r.stdout
    assert r.stdout.endswith("prints all of it]\n")


def test_no_declared_budget_falls_back_to_twenty_kilobytes():
    mod = _mod()
    text = "x" * 50 + "\n"
    assert mod.fit(text * 1000, mod.FALLBACK_BUDGET).count("\n") < 1000
    assert len(mod.fit(text * 1000, mod.FALLBACK_BUDGET).encode()) <= 20000
    assert mod.fit(text, 20000) == text


def test_the_real_pack_is_printed_within_the_budget(tmp_path):
    """This checkout's harness.yaml and docs, the pack built by the harness this test runs on."""
    root = _checkout(tmp_path, python=f'exec "{sys.executable}" "$@"')
    r = _hook(root)
    assert r.returncode == 0 and r.stderr == ""
    assert r.stdout.startswith("# Context pack")
    from spicexplorer_harness import load

    budget = load(root).memory_pack_budget or _mod().FALLBACK_BUDGET
    assert 0 < len(r.stdout.encode()) <= budget


def _session_start() -> dict:
    hooks = json.loads((REPO / ".claude" / "settings.json").read_text())["hooks"]["SessionStart"]
    assert isinstance(hooks, list) and len(hooks) == 1
    return hooks[0]


def test_settings_json_runs_the_hook_at_session_start():
    entry = _session_start()
    assert set(entry["matcher"].split("|")) == {"startup", "clear", "compact"}
    (hook,) = entry["hooks"]
    assert hook["type"] == "command" and isinstance(hook["timeout"], int)
    assert "scripts/session_pack.py" in hook["command"]
    assert hook["timeout"] > _mod().TIMEOUT


def test_the_settings_command_exits_0_with_or_without_the_script(tmp_path):
    (hook,) = _session_start()["hooks"]
    for project in (_checkout(tmp_path), tmp_path / "no-such-checkout"):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        r = subprocess.run(["sh", "-c", hook["command"]], capture_output=True, text=True,
                           env=env, timeout=60, check=False)
        assert (r.returncode, r.stdout, r.stderr) == (0, "", ""), project
