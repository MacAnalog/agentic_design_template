"""`tests/conftest.py`: each checkout gets its own pytest base folder under the scratch root.

template#43 — the folder was `$SX_SCRATCH/pytest/<checkout folder name>`, and pytest empties its
base folder when a run starts, so two checkouts with the same folder name emptied each other's
scratch, a run still in progress included.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

CONFTEST = Path(__file__).resolve().parent / "conftest.py"


def _basetemp_of(checkout: Path, name: str) -> Path:
    """Copy this conftest into `checkout/tests/` and ask its hook where pytest scratch would go."""
    (checkout / "tests").mkdir(parents=True)
    copy = checkout / "tests" / "conftest.py"
    shutil.copyfile(CONFTEST, copy)
    spec = importlib.util.spec_from_file_location(name, copy)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    config = SimpleNamespace(option=SimpleNamespace(basetemp=None))
    mod.pytest_configure(config)
    return Path(config.option.basetemp)


def test_two_checkouts_with_the_same_folder_name_get_different_base_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("SX_SCRATCH", str(tmp_path / "scratch"))
    one = _basetemp_of(tmp_path / "a" / "fresh", "conftest_copy_a")
    two = _basetemp_of(tmp_path / "b" / "fresh", "conftest_copy_b")
    assert one != two
    for base in (one, two):
        assert base.parent == tmp_path / "scratch" / "pytest"
        assert re.fullmatch(r"fresh-[0-9a-f]{8}", base.name), base.name   # still readable
