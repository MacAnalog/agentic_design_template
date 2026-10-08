#!/usr/bin/env python3
"""The SessionStart hook: hand a new session this design's bare context pack, cut to its budget.

`make pack` at task start was a rule each agent had to remember. `.claude/settings.json` runs this
script when a session starts, after `/clear` and after a compaction; what it prints on stdout is
added to the session's context. `make pack K="…"` stays the way to re-key the pack mid-task.

It never blocks a session and prints nothing on any error. Exit status is always 0:

- no `harness.yaml`, or no executable `.venv/bin/python` (a checkout before `make init`): nothing;
- the pack exits non-zero, raises, or takes longer than `TIMEOUT` seconds: nothing;
- otherwise: the pack as `make pack` prints it, cut at a line boundary to `memory.pack_budget`
  bytes (`FALLBACK_BUDGET` when the design declares none), the last line saying it was cut.

Standard library only: it runs under the system `python3`, and the checkout's venv interpreter
builds the pack in a child process that `TIMEOUT` bounds.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TIMEOUT = 20.0  # seconds; the hook's own timeout in .claude/settings.json is 30
FALLBACK_BUDGET = 20000  # bytes, when harness.yaml declares no memory.pack_budget

# Run by the venv interpreter: the budget on the first line, then the pack `make pack` prints.
_RENDER = (
    "import sys\n"
    "from spicexplorer_harness import cli, load\n"
    "print(load(sys.argv[1]).memory_pack_budget, flush=True)\n"
    "sys.exit(cli.main(['--repo', sys.argv[1], 'pack']))\n"
)


def fit(text: str, budget: int) -> str:
    """`text` if it fits in `budget` bytes; else its first lines and one line saying it was cut,
    together at most `budget` bytes."""
    data = text.encode()
    if len(data) <= budget:
        return text
    note = (
        f"[the pack is cut here at memory.pack_budget = {budget} bytes; "
        f"`make pack` prints all of it]\n"
    )
    room = budget - len(note.encode())
    if room <= 0:
        return ""
    head = data[:room].decode(errors="ignore")
    return head[: head.rfind("\n") + 1] + note


def pack(root: Path = REPO, timeout: float = TIMEOUT) -> str:
    """The text the hook prints for the checkout at `root`: "" whenever there is nothing to say."""
    py = root / ".venv" / "bin" / "python"
    if not (root / "harness.yaml").is_file() or not os.access(py, os.X_OK):
        return ""
    try:
        r = subprocess.run(
            [str(py), "-c", _RENDER, str(root)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if r.returncode != 0:
        return ""
    first, _, body = r.stdout.partition("\n")
    try:
        budget = int(first.strip())
    except ValueError:
        return ""
    return fit(body, budget if budget > 0 else FALLBACK_BUDGET)


def main() -> int:
    try:
        sys.stdout.write(pack())
        sys.stdout.flush()
    except BaseException:  # noqa: BLE001, S110 - a session start is never blocked or told about it
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
