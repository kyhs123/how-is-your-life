"""index.py —— SQLite 索引。

**索引不是真相源。** 真相源永远是 vault/now/ 里的 markdown（DESIGN.md §3.5）。
索引只是「目录页」：可以随时删掉，用 `life reindex` 从 markdown 重新长出来。

第 1 周只建三张表：
- entries        每条记录一行，方便以后按时间/情绪/目标查
- entries_fts    全文检索（FTS5），以后按关键词搜
- usage          每次调模型花了多少 token，对应 §6.3「成本可观测」

chapters / goals / vec_entries 三张表第 2、3 周再加，现在建了也是空的。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from life import store


class 索引错误(Exception):
    """索引层面的问题。注意：索引坏了不该影响你的记录文件。"""


# 建表语句。照 DESIGN.md §3.5，只多了两处第 1 周必须的：
#   entries.body      正文存在这里，全文检索要用
#   entries_fts.entry_id  让检索结果能对上某条记录（FTS5 本身不存这个）
建表语句 = """
CREATE TABLE IF NOT EXISTS entries(
    id TEXT PRIMARY KEY,
    ts TEXT,
    part TEXT,
    did TEXT,
    minutes INT,
    outcome TEXT,
    level INT,
    goal TEXT,
    chapter TEXT,
    valence REAL,
    arousal REAL,
    trigger TEXT,
    private INT,
    status TEXT,
    body TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts
USING fts5(did, body, entry_id UNINDEXED, tokenize='trigram');

CREATE TABLE IF NOT EXISTS usage(
    ts TEXT,
    task TEXT,
    model TEXT,
    tokens_in INT,
    tokens_out INT
);
"""


def 连接索引() -> sqlite3.Connection:
    """打开索引库（不存在就建）。"""
    vault = store.确保vault就绪()
    路径 = vault / "index.sqlite"
    try:
        连接 = sqlite3.connect(路径)
    except sqlite3.Error as 错误:
        raise 索引错误(f"打不开索引库 {路径}：{错误}") from 错误
    连接.row_factory = sqlite3.Row
    建表(连接)
    return 连接


def 建表(连接: sqlite3.Connection) -> None:
    """保证三张表都在。用 IF NOT EXISTS，所以重复调用没副作用。"""
    try:
        连接.executescript(建表语句)
        连接.commit()
    except sqlite3.Error as 错误:
        raise 索引错误(f"建索引表失败：{错误}") from 错误


def 写入条目(连接: sqlite3.Connection, 条目: dict) -> None:
    """把一条记录写进索引（已经有同 id 的就覆盖）。"""
    try:
        with 连接:  # with 连接 会自动 commit，出错自动回滚
            连接.execute(
                """
                INSERT OR REPLACE INTO entries
                    (id, ts, part, did, minutes, outcome, level, goal, chapter,
                     valence, arousal, trigger, private, status, body)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    条目["id"],
                    条目["ts"],
                    条目["part"],
                    条目["did"],
                    条目["minutes"],
                    条目["outcome"],
                    条目["level"],
                    条目["goal"],
                    条目["chapter"],
                    条目["emotion"]["valence"],
                    条目["emotion"]["arousal"],
                    条目["emotion"]["trigger"],
                    1 if 条目["private"] else 0,
                    条目["status"],
                    条目["body"],
                ),
            )
            # 全文索引里同一个 id 只能有一行
            连接.execute("DELETE FROM entries_fts WHERE entry_id = ?", (条目["id"],))
            连接.execute(
                "INSERT INTO entries_fts (did, body, entry_id) VALUES (?,?,?)",
                (条目["did"], 条目["body"], 条目["id"]),
            )
    except sqlite3.Error as 错误:
        raise 索引错误(f"写索引失败（记录 {条目.get('id', '?')}）：{错误}") from 错误


def 删除条目(连接: sqlite3.Connection, 记录id: str) -> None:
    """从索引里删掉一条（不给用户用，是 reindex 之前的清理步骤）。"""
    with 连接:
        连接.execute("DELETE FROM entries WHERE id = ?", (记录id,))
        连接.execute("DELETE FROM entries_fts WHERE entry_id = ?", (记录id,))


def 记录用量(
    连接: sqlite3.Connection, 任务: str, 模型: str, 输入token: int, 输出token: int
) -> None:
    """记一笔模型调用。DESIGN.md §6.3：用户看不到花费就不敢用。"""
    with 连接:
        连接.execute(
            "INSERT INTO usage (ts, task, model, tokens_in, tokens_out) VALUES (?,?,?,?,?)",
            (store.时间文本(store.现在()), 任务, 模型, 输入token, 输出token),
        )


def 重建索引() -> dict:
    """`life reindex`：把索引清空，从 vault/now/ 的 markdown 全部重读一遍。

    DESIGN.md §3.5 的硬性验收项。索引删了、坏了、或者你手改了 markdown，
    跑这个命令就能修好。
    """
    文件们 = store.遍历条目()
    失败: list[str] = []
    成功 = 0

    连接 = 连接索引()
    try:
        with 连接:
            连接.execute("DELETE FROM entries")
            连接.execute("DELETE FROM entries_fts")

        for 路径 in 文件们:
            try:
                条目 = store.读条目(路径)
            except store.存储错误 as 错误:
                失败.append(f"{路径} —— {错误}")
                continue
            写入条目(连接, 条目)
            成功 += 1
    finally:
        连接.close()

    return {"扫描": len(文件们), "成功": 成功, "失败": 失败}


def 统计(连接: sqlite3.Connection) -> dict:
    """给 `life 状态` 用的几个数字。"""
    一行 = 连接.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM entries) AS 条目数,
          (SELECT COUNT(*) FROM entries WHERE private = 1) AS 私密条数,
          (SELECT COUNT(*) FROM entries WHERE status = 'needs_review') AS 待看条数,
          (SELECT COALESCE(SUM(tokens_in + tokens_out), 0) FROM usage) AS 总token,
          (SELECT COUNT(*) FROM usage) AS 调用次数
        """
    ).fetchone()
    return dict(一行) if 一行 else {}


def 库文件() -> Path:
    """索引库在哪。"""
    return store.确保vault就绪() / "index.sqlite"
