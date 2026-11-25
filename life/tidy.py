"""tidy.py —— 瘦身：清理「删了也能重建」的东西。

只删**能重建**的，不碰任何记录：

| 删什么 | 为什么能删 | 代价 |
|---|---|---|
| 旧的抽取缓存 | 它只干两件事：省一次模型调用、认出重复提交 | 下次记同样的内容会重新抽一次 |
| 孤儿 media | 对应的记录已经不存在了，那些全文没人引用 | 无 |
| 空目录 | 删完文件留下的空壳 | 无 |

**绝不删**：`now/`（记录）、`chapters/`、`goals/`、`core.md`、`portrait/`、`media/` 里有主的那部分。

设计取舍：不做自动清理（后台偷偷删东西最容易让人不信任）。
必须你点按钮 / 敲命令，而且默认**先干跑给你看数字**。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from life import config, store

默认保留天数 = 90


def 缓存文件们() -> list[Path]:
    目录 = store.确保vault就绪() / "缓存" / "抽取"
    return sorted(p for p in 目录.rglob("*.json") if p.is_file()) if 目录.exists() else []


def media文件们() -> list[Path]:
    """media 里的素材文件。排除关联表自己（它不是素材）。"""
    目录 = store.确保vault就绪() / "media"
    if not 目录.exists():
        return []
    return sorted(p for p in 目录.glob("*") if p.is_file() and p.name != "关联.json")


def 记录id们() -> set[str]:
    """现在还存在的记录 id（文件名就是 id）。"""
    return {p.stem for p in store.遍历条目()}


def 孤儿media(已有id们: set[str] | None = None) -> tuple[list[Path], int]:
    """（确认可删的孤儿，未登记的文件数）。

    **判定必须保守**：media 的文件名用的是「输入 id」，记录用的是「记录 id」，
    光看文件名会把正常文件误判成孤儿（真踩过：差点删掉简历的全文）。
    所以：
      - 关联表里登记过，且那些记录**一个都不在了** → 才是孤儿
      - 关联表里没有（老文件 / 早期版本没登记） → **不动**，只数出来告诉你
    """
    id们 = 已有id们 if 已有id们 is not None else 记录id们()
    关联 = store.读media关联()

    孤儿: list[Path] = []
    未登记 = 0
    for 文件 in media文件们():
        登记 = 关联.get(文件.name)
        if 登记 is None:
            未登记 += 1
            continue
        if not (set(登记) & id们):
            孤儿.append(文件)
    return 孤儿, 未登记


def 扫描(保留天数: int = 默认保留天数) -> dict:
    """看看能清掉多少（不动任何文件）。"""
    现在 = time.time()
    期限 = 现在 - 保留天数 * 86400
    缓存 = 缓存文件们()
    旧缓存 = [p for p in 缓存 if p.stat().st_mtime < 期限]
    孤儿, 未登记 = 孤儿media()

    return {
        "缓存总数": len(缓存),
        "缓存可清": len(旧缓存),
        "缓存字节": sum(p.stat().st_size for p in 缓存),
        "可清缓存字节": sum(p.stat().st_size for p in 旧缓存),
        "媒体总数": len(media文件们()),
        "孤儿媒体": len(孤儿),
        "孤儿字节": sum(p.stat().st_size for p in 孤儿),
        "未登记媒体": 未登记,
    }


def 执行(保留天数: int = 默认保留天数, *, 干跑: bool = False) -> dict:
    """真删（干跑时只数不改）。"""
    现在 = time.time()
    期限 = 现在 - 保留天数 * 86400

    删缓存 = [p for p in 缓存文件们() if p.stat().st_mtime < 期限]
    删孤儿, _未登记 = 孤儿media()
    删字节 = sum(p.stat().st_size for p in 删缓存 + 删孤儿)

    if not 干跑:
        for p in 删缓存 + 删孤儿:
            try:
                p.unlink()
            except OSError:
                pass
        _清空目录()

    return {
        "缓存": len(删缓存),
        "孤儿媒体": len(删孤儿),
        "字节": 删字节,
        "干跑": 干跑,
        "保留天数": 保留天数,
    }


def _清空目录() -> None:
    """删完文件，把空的桶目录和空目录一并收掉。"""
    根 = store.确保vault就绪()
    for 顶层 in ("缓存/抽取", "media"):
        目录 = 根 / 顶层
        if not 目录.exists():
            continue
        for 子 in sorted(目录.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if 子.is_dir() and not any(子.iterdir()):
                try:
                    子.rmdir()
                except OSError:
                    pass


def 人话(数字: int) -> str:
    """字节数变人话。"""
    for 单位 in ("B", "KB", "MB", "GB"):
        if 数字 < 1024:
            return f"{数字:.0f}{单位}" if 单位 == "B" else f"{数字:.1f}{单位}"
        数字 /= 1024
    return f"{数字:.1f}TB"
