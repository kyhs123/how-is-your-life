"""测试的公共准备。

关键一条：每个测试都用一个临时的空目录当工作区（LIFE_HOME），
这样跑测试永远不会碰到你真正的 vault/。
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def 临时工作区(tmp_path, monkeypatch):
    """给这个测试一个干净的工作区，用完自动扔掉。"""
    monkeypatch.setenv("LIFE_HOME", str(tmp_path))
    return tmp_path
