"""index.py —— SQLite 索引。

**索引不是真相源。** 真相源永远是 vault/now/ 里的 markdown（DESIGN.md §3.5）。
索引只是「目录页」：可以随时删掉，用 `life reindex` 从 markdown 重新长出来。

四张表：
- entries        每条记录一行，方便按时间/情绪/目标/关键词查
- entries_fts    全文检索（FTS5 + trigram 分词），中文不用装分词库也能搜
- vec_entries    向量（§4.3 第一路检索用），没配向量接口时是空的
- usage          每次调模型花多少 token，对应 §6.3「成本可观测」

chapters / goals 两张表要等第 3 周，现在建了也是空的。
"""

from __future__ import annotations

import array
import json
import sqlite3
from pathlib import Path

from life import store


class 索引错误(Exception):
    """索引层面的问题。注意：索引坏了不该影响你的记录文件。"""


# 建表语句。照 DESIGN.md §3.5，只多了几处检索必须的：
#   entries.body       正文存在这里，全文检索要用
#   entries.anchors    锚点的 JSON，§4.3 的「anchors 过滤」要用
#   entries_fts.entry_id  让检索结果能对上某条记录（FTS5 本身不存这个）
#   vec_entries        向量（第 2 周的三路检索第一路）
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
    body TEXT,
    anchors TEXT,
    quote TEXT,
    "when" TEXT
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

CREATE TABLE IF NOT EXISTS vec_entries(
    entry_id TEXT PRIMARY KEY,
    embedding BLOB,
    model TEXT,
    dim INT
);

CREATE TABLE IF NOT EXISTS chapters(
    id TEXT PRIMARY KEY,
    title TEXT,
    status TEXT,
    level_max INT,
    entry_count INT,
    last_evidence TEXT
);

CREATE TABLE IF NOT EXISTS goals(
    id TEXT PRIMARY KEY,
    title TEXT,
    horizon TEXT,
    status TEXT,
    due TEXT
);

CREATE TABLE IF NOT EXISTS core(
    name TEXT PRIMARY KEY,
    level_max INT,
    first_at TEXT,
    last_at TEXT,
    status TEXT
);
"""

# 老库升级用：表已经存在时，这些列要补上去（CREATE TABLE IF NOT EXISTS 不会补列）
后续补的列 = {
    "entries": [
        ("body", "TEXT"),
        ("anchors", "TEXT"),
        ("quote", "TEXT"),
        ("when", "TEXT"),
    ],
}



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
    """保证表都在，老库缺的列补上。用 IF NOT EXISTS，所以重复调用没副作用。"""
    try:
        连接.executescript(建表语句)
        for 表名, 列们 in 后续补的列.items():
            已有 = {行["name"] for 行 in 连接.execute(f"PRAGMA table_info({表名})")}
            for 列名, 类型 in 列们:
                if 列名 not in 已有:
                    # 列名都加双引号：when 是 SQL 关键字，不加引号会报语法错
                    连接.execute(f'ALTER TABLE {表名} ADD COLUMN "{列名}" {类型}')
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
                     valence, arousal, trigger, private, status, body, anchors, quote,
                     "when")
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    json.dumps(条目["anchors"], ensure_ascii=False),
                    条目["emotion"]["quote"],
                    条目.get("when", ""),
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
    """`life reindex`：把索引清空，从 markdown 全部重读一遍。

    DESIGN.md §3.5 的硬性验收项。索引删了、坏了、或者你手改了 markdown，
    跑这个命令就能修好。记录、主题、目标、底色都在这里一起重建。
    """
    文件们 = store.遍历条目()
    失败: list[str] = []
    成功 = 0

    连接 = 连接索引()
    try:
        with 连接:
            连接.execute("DELETE FROM entries")
            连接.execute("DELETE FROM entries_fts")
            连接.execute("DELETE FROM chapters")
            连接.execute("DELETE FROM goals")
            连接.execute("DELETE FROM core")

        for 路径 in 文件们:
            try:
                条目 = store.读条目(路径)
            except store.存储错误 as 错误:
                失败.append(f"{路径} —— {错误}")
                continue
            写入条目(连接, 条目)
            成功 += 1

        章节数 = 0
        for 章节 in store.全部章节():
            写入章节(连接, 章节)
            章节数 += 1

        目标数 = 0
        for 目标 in store.全部目标():
            写入目标(连接, 目标)
            目标数 += 1

        底色数 = 0
        for 项 in store.读底色项():
            写入底色项(连接, 项)
            底色数 += 1
    finally:
        连接.close()

    return {
        "扫描": len(文件们),
        "成功": 成功,
        "失败": 失败,
        "章节": 章节数,
        "目标": 目标数,
        "底色": 底色数,
    }


def 写入章节(连接: sqlite3.Connection, 章节: dict) -> None:
    连接.execute(
        "INSERT OR REPLACE INTO chapters (id, title, status, level_max, entry_count, last_evidence) "
        "VALUES (?,?,?,?,?,?)",
        (
            章节["id"],
            章节["title"],
            章节["status"],
            章节["level_max"],
            章节["entry_count"],
            章节["last_evidence"],
        ),
    )
    连接.commit()


def 写入目标(连接: sqlite3.Connection, 目标: dict) -> None:
    连接.execute(
        "INSERT OR REPLACE INTO goals (id, title, horizon, status, due) VALUES (?,?,?,?,?)",
        (目标["id"], 目标["title"], 目标["horizon"], 目标["status"], 目标["due"]),
    )
    连接.commit()


def 写入底色项(连接: sqlite3.Connection, 项: dict) -> None:
    """底色那一条，顺带记下它的首次/最近时间（从证据行里读不出来就算空）。"""
    连接.execute(
        "INSERT OR REPLACE INTO core (name, level_max, first_at, last_at, status) "
        "VALUES (?,?,?,?,?)",
        (项["name"], 0, "", "", "fresh"),
    )
    连接.commit()


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


# ── 向量（§4.3 第一路检索）─────────────────────────────────────
#
# 存法：float32 小端字节串塞进 BLOB。1000 条 × 1024 维 ≈ 4MB，够用。
# 不用 sqlite-vec 扩展：那个要额外装二进制，而「朴素余弦」在这个量级上完全够
# （DESIGN.md §3.5 写的正是「sqlite-vec 或朴素余弦」）。


def 写向量(
    连接: sqlite3.Connection, 记录id: str, 向量: list[float], 模型: str
) -> None:
    with 连接:
        连接.execute(
            "INSERT OR REPLACE INTO vec_entries (entry_id, embedding, model, dim) VALUES (?,?,?,?)",
            (记录id, array.array("f", 向量).tobytes(), 模型, len(向量)),
        )


def 读全部向量(连接: sqlite3.Connection) -> dict[str, list[float]]:
    """把库里所有向量读进内存（几千条的量级，内存放得下）。"""
    结果: dict[str, list[float]] = {}
    for 行 in 连接.execute("SELECT entry_id, embedding FROM vec_entries"):
        缓冲 = array.array("f")
        缓冲.frombytes(行["embedding"])
        结果[行["entry_id"]] = list(缓冲)
    return 结果


def 清空向量(连接: sqlite3.Connection) -> None:
    with 连接:
        连接.execute("DELETE FROM vec_entries")


def 向量条数(连接: sqlite3.Connection) -> int:
    return int(连接.execute("SELECT COUNT(*) FROM vec_entries").fetchone()[0])


# ── 检索用的小工具 ────────────────────────────────────────────


def 行转条目(行: sqlite3.Row) -> dict:
    """把数据库一行转成和 markdown 解析结果同样形状的 dict。

    这样检索层拿到的东西，和 store.读条目() 读出来的一样，调用方不用区分。
    """
    try:
        锚点 = json.loads(行["anchors"] or "{}")
    except (json.JSONDecodeError, TypeError):
        锚点 = {}
    return {
        "id": 行["id"],
        "ts": 行["ts"],
        "when": 行["when"] or "",
        "part": 行["part"],
        "did": 行["did"],
        "minutes": 行["minutes"],
        "outcome": 行["outcome"],
        "level": 行["level"],
        "goal": 行["goal"],
        "chapter": 行["chapter"],
        "anchors": {
            "tech": list(锚点.get("tech") or []),
            "people": list(锚点.get("people") or []),
            "link": str(锚点.get("link") or ""),
        },
        "emotion": {
            "valence": 行["valence"] or 0.0,
            "arousal": 行["arousal"] or 0.0,
            "trigger": 行["trigger"] or "",
            "quote": 行["quote"] or "",
        },
        "blockers": [],
        "private": bool(行["private"]),
        "status": 行["status"],
        "body": 行["body"] or "",
    }


def 取条目(连接: sqlite3.Connection, 记录id: str) -> dict | None:
    行 = 连接.execute("SELECT * FROM entries WHERE id = ?", (记录id,)).fetchone()
    return 行转条目(行) if 行 else None
