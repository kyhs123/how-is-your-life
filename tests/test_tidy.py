"""测瘦身——只看磁盘上的结果：文件是被删了还是留着。"""

from __future__ import annotations

import os
import time
from datetime import timedelta

from typer.testing import CliRunner

from life import cli, extract, store, tidy

运行 = CliRunner()


def _造记录(标题: str = "一条记录") -> str:
    编号, 时间 = store.分配id(store.现在())
    store.写条目(
        store.新建条目(id=编号, ts=store.时间文本(时间), did=标题, body=标题)
    )
    return 编号


def _造缓存(指纹: str, *, 天前: int = 0) -> "object":
    路径 = extract.缓存路径(指纹)
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text('{"entry_paths": []}', encoding="utf-8")
    旧时间 = time.time() - 天前 * 86400
    os.utime(路径, (旧时间, 旧时间))
    return 路径


def test_缓存按指纹分桶(临时工作区):
    路径 = extract.缓存路径("ab" + "c" * 62)
    assert 路径.parent.name == "ab", "缓存要按指纹前两位分目录"
    assert 路径.name.endswith(".json")


def test_老版扁平缓存能被读到并搬进桶(临时工作区):
    指纹 = "cd" + "e" * 62
    老位置 = extract.缓存目录() / f"{指纹}.json"
    老位置.parent.mkdir(parents=True, exist_ok=True)
    老位置.write_text('{"entry_paths": ["now/x.md"]}', encoding="utf-8")

    读到 = extract.读缓存(指纹)

    assert 读到 and 读到["entry_paths"] == ["now/x.md"]
    assert not 老位置.exists(), "老文件应该被搬走"
    assert extract.缓存路径(指纹).exists()


def test_超过保留天数的缓存会被清掉(临时工作区):
    旧 = _造缓存("aa" + "1" * 62, 天前=120)
    新 = _造缓存("bb" + "2" * 62, 天前=1)

    运行.invoke(cli.app, ["tidy", "--days", "90"])

    assert not 旧.exists(), "120 天前的缓存该清掉"
    assert 新.exists(), "1 天前的缓存要留着"


def test_登记的孤儿媒体会被清掉没登记的不动(临时工作区):
    media = store.确保vault就绪() / "media"

    # ① 记录还在 → 全文必须留
    活记录 = _造记录("有主的记录")
    (media / f"{活记录}.md").write_text("正文", encoding="utf-8")
    store.写media关联(f"{活记录}.md", [活记录])

    # ② 记录已经被删 → 全文是孤儿
    (media / "20200101-000000.md").write_text("以前的", encoding="utf-8")
    store.写media关联("20200101-000000.md", ["20200101-000000"])

    # ③ 压根没登记过 → 分不清，不许动
    (media / "来历不明.md").write_text("?", encoding="utf-8")

    结果 = tidy.执行(保留天数=90)

    assert (media / f"{活记录}.md").exists(), "有主的不许删"
    assert not (media / "20200101-000000.md").exists(), "孤儿该删"
    assert (media / "来历不明.md").exists(), "没登记的保守留着"
    assert 结果["孤儿媒体"] == 1


def test_干跑一个文件都不动(临时工作区):
    旧 = _造缓存("cc" + "3" * 62, 天前=200)
    运行.invoke(cli.app, ["tidy", "--dry-run"])
    assert 旧.exists(), "--dry-run 不许动文件"


def test_记录不会被瘦身碰到(临时工作区):
    编号 = _造记录("这条必须活着")
    运行.invoke(cli.app, ["tidy", "--days", "0"])
    assert store.找条目文件(编号) is not None
