"""测 vault 结构——只验「用户能看到的东西」：目录在不在、占位文件在不在、手改会不会被覆盖。"""

from __future__ import annotations

from life import store


def test_第一次运行会把目录和占位文件建出来(临时工作区):
    vault = store.确保vault就绪()

    for 子目录 in ("inbox", "now", "chapters", "goals", "portrait", "media"):
        assert (vault / 子目录).is_dir(), f"{子目录} 没建出来"
    for 文件 in ("core.md", "corrections.md", "changelog.md"):
        assert (vault / 文件).is_file(), f"{文件} 没建出来"


def test_手改过的占位文件不会被覆盖(临时工作区):
    """你在 core.md 里写的东西，程序不能给你抹掉。"""
    vault = store.确保vault就绪()
    (vault / "core.md").write_text("# 我自己写的底色\n", encoding="utf-8")

    store.确保vault就绪()

    assert "我自己写的底色" in (vault / "core.md").read_text(encoding="utf-8")
