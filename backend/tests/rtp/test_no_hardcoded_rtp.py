import inspect

import pytest

from plugins.games.mines.plugin import MinesAdapter
from plugins.games.crash.plugin import CrashAdapter
from plugins.games.upgrade.plugin import UpgradeAdapter
from plugins.games.shell.plugin import ShellAdapter


@pytest.mark.parametrize("adapter_cls", [MinesAdapter, CrashAdapter, UpgradeAdapter, ShellAdapter])
def test_no_hardcoded_rtp(adapter_cls):
    src = inspect.getsource(adapter_cls)
    for bad in ("0.80", "0.85", "0.88", "0.90"):
        assert bad not in src
