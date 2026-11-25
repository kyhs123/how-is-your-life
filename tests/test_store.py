"""测 store.py：vault 结构、markdown 读写、防重复用的指纹。"""

from __future__ import annotations

import pytest

from life import store


def _造一条(**改):
    """造一条最小可用的 entry，给各个测试当底稿。"""
    字段 = {
        "id": "20261125-143200",
        "ts": "2026-11-25T14:32:00+08:00",
        "part": "record",
        "did": "接通 OAuth 登录，卡点为 state 参数签名",
        "minutes": 240,
        "outcome": "done",
        "anchors": {"tech": ["OAuth", "state 参数"], "people": [], "link": ""},
        "emotion": {"valence": -0.5, "arousal": 0.6, "trigger": "文档不清", "quote": ""},
        "level": 2,
        "goal": "",
        "chapter": "",
        "blockers": ["state 参数要签名"],
        "private": False,
        "status": "settled",
        "body": "接通 OAuth 登录，卡点为 state 参数签名；后端已通，前端待接。",
    }
    字段.update(改)
    return store.新建条目(**字段)


def test_建vault结构(临时工作区):
    """第一次运行要能把目录和占位文件都建出来。"""
    vault = store.确保vault就绪()

    for 子目录 in ("inbox", "now", "chapters", "goals", "portrait", "media"):
        assert (vault / 子目录).is_dir(), f"{子目录} 没建出来"
    for 文件 in ("core.md", "corrections.md", "changelog.md"):
        assert (vault / 文件).is_file(), f"{文件} 没建出来"

    # 再跑一次不能出错，也不能把已有内容改掉
    (vault / "core.md").write_text("# 我自己写的", encoding="utf-8")
    store.确保vault就绪()
    assert (vault / "core.md").read_text(encoding="utf-8") == "# 我自己写的"


def test_写了再读回来字段不变(临时工作区):
    """markdown 存下去再读上来，每个字段都要对得上。"""
    原 = _造一条()
    路径 = store.写条目(原)
    读回 = store.读条目(路径)

    assert 路径.parent.name == "2026-11"
    assert 路径.name == "20261125-143200.md"
    assert 读回["did"] == 原["did"]
    assert 读回["minutes"] == 240
    assert 读回["anchors"]["tech"] == ["OAuth", "state 参数"]
    assert 读回["emotion"]["valence"] == -0.5
    assert 读回["blockers"] == ["state 参数要签名"]
    assert 读回["private"] is False
    assert 读回["body"] == "接通 OAuth 登录，卡点为 state 参数签名；后端已通，前端待接。"


def test_正文为空时用did顶上(临时工作区):
    条目 = _造一条(body="")
    assert 条目["body"] == 条目["did"]


def test_指纹一样就认成同一条(临时工作区):
    """空格和换行不该影响「是不是同一条」。"""
    assert store.内容哈希("今天 很累 ") == store.内容哈希("今天很累")
    assert store.内容哈希("今天很累") != store.内容哈希("今天很困")


def test_文件名和id对不上要报错(临时工作区):
    """有人手动改过文件名的话，索引会和文件对不上，所以要拦住。"""
    条目 = _造一条()
    路径 = store.写条目(条目)
    错的路径 = 路径.with_name("20260101-000000.md")
    路径.replace(错的路径)

    with pytest.raises(store.存储错误):
        store.读条目(错的路径)


def test_同一个文件名分配id会往后挪一秒(临时工作区):
    """一段话被拆成几条时，不能都写进同一个文件。"""
    时间 = store.现在()
    第一个, 时间 = store.分配id(时间)
    条目 = _造一条(id=第一个, ts=store.时间文本(时间))
    store.写条目(条目)

    第二个, _ = store.分配id(时间)
    assert 第一个 != 第二个
    assert (store.条目路径(第一个, 条目["ts"])).exists()
