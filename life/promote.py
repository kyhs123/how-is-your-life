"""promote.py —— 固化与晋升（DESIGN.md §4.6 / §3.2）。

两条命令：

    life settle --week   把本周的记录归纳成「主题」，够条件的写成提名
    life promote         一条条处理提名：要 / 不要

**绝不自动晋升。** 设计里写得很明确：系统提名 → 用户确认 → 生效。
因为「我以为你重视这个」经常是错的，错判一次用户就不再信任系统。

所以这个文件的所有写操作都只发生在「用户点了要」之后。
settle 本身只写 changelog 里的一行提名，不动任何记录。
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from life import config, extract, index, llm, store


class 晋升错误(Exception):
    """晋升流程里的问题（找不到提名、条件不够之类）。"""


# ── 本周记录 ─────────────────────────────────────────────────


def 近期条目(天数: int = 7) -> list[dict]:
    """最近 N 天的记录（不含私密，§8）。"""
    连接 = index.连接索引()
    try:
        最早 = (store.现在() - timedelta(days=天数)).date().isoformat()
        行们 = 连接.execute(
            "SELECT id FROM entries WHERE private = 0 AND substr(ts, 1, 10) >= ? ORDER BY ts",
            (最早,),
        ).fetchall()
        return [e for e in (index.取条目(连接, 行["id"]) for 行 in 行们) if e]
    finally:
        连接.close()


# ── 提名（life settle）───────────────────────────────────────


def 提名(天数: int = 7) -> dict:
    """读本周记录 → 让模型找主题 → 用关键词回连全库 → 检查 §3.2 的条件 → 写成提名。

    为什么要有「回连全库」这一步：
        §4.6 说 settle 每周跑一次、读**本周**记录；§3.2 却要求晋升必须「跨 ≥2 个月」。
        只看一周，永远不可能跨两个月。所以分工是：
        本周记录用来**发现**主题，主题里的关键词用来把**历史记录**串起来，
        条件检查跑在全库关联出来的那一批上。
    """
    条目们 = 近期条目(天数)
    if len(条目们) < 2:
        return {
            "主题数": 0,
            "提名": [],
            "没提名": [],
            "说明": f"最近 {天数} 天只有 {len(条目们)} 条记录，太少，先不用固化。",
        }

    主题们 = _找主题(条目们)
    if not 主题们:
        return {"主题数": 0, "提名": [], "没提名": [], "说明": "这一段里没有重复出现的主题。"}

    按id = {e["id"]: e for e in 条目们}
    全库 = _全部条目()
    已拒绝 = _被拒绝过的标题()

    提名们: list[dict] = []
    没提名: list[dict] = []

    for 主题 in 主题们:
        标题 = str(主题.get("title") or "").strip()
        if not 标题:
            continue

        本批 = [按id[i] for i in (主题.get("entry_ids") or []) if i in 按id]
        关联 = _回连(本批, 主题.get("keywords") or [], 全库)
        if not 关联:
            continue

        条件 = 检查条件(关联)
        记录 = {
            "标题": 标题,
            "摘要": str(主题.get("summary") or ""),
            "产出物": str(主题.get("artifact") or ""),
            "关键词": [str(k) for k in (主题.get("keywords") or [])],
            "条目ids": [e["id"] for e in 关联],
            "月份": sorted({e["ts"][:7] for e in 关联}),
            "条数": len(关联),
            "最高档": max(e["level"] for e in 关联),
            "条件": 条件,
        }

        if 标题 in 已拒绝:
            没提名.append({**记录, "原因": "你之前拒绝过，不再重复提"})
            continue
        if not 条件["全满足"]:
            没提名.append({**记录, "原因": "缺：" + "、".join(条件["缺"])})
            continue

        提名们.append(记录)
        _存提名(记录)
        store.追加日志(f"提名：{标题} → 章节（{_依据文字(记录)}）")

    return {
        "主题数": len(主题们),
        "提名": 提名们,
        "没提名": 没提名,
        "说明": "",
    }


def _全部条目() -> list[dict]:
    """索引里所有非私密记录，按时间排。回连历史要用。"""
    连接 = index.连接索引()
    try:
        行们 = 连接.execute(
            "SELECT id FROM entries WHERE private = 0 ORDER BY ts"
        ).fetchall()
        return [e for e in (index.取条目(连接, 行["id"]) for 行 in 行们) if e]
    finally:
        连接.close()


def _回连(本批: list[dict], 关键词: list, 全库: list[dict]) -> list[dict]:
    """用主题的关键词把历史上同类记录也串起来。

    没有这一步，「跨 ≥2 个月」永远不可能满足——因为 settle 只看本周。
    关键词命中 did 或正文就算，宁宽勿窄：多串一条只是多一份证据。
    """
    已含 = {e["id"] for e in 本批}
    关联 = list(本批)
    词们 = [str(k).strip() for k in 关键词 if str(k).strip()]

    for 条目 in 全库:
        if 条目["id"] in 已含:
            continue
        文本 = 条目["did"] + " " + 条目["body"]
        if any(词 in 文本 for 词 in 词们):
            关联.append(条目)

    关联.sort(key=lambda e: e["ts"])
    return 关联


def 检查条件(条目们: list[dict]) -> dict:
    """DESIGN.md §3.2「当下 → 章节」三条，必须同时满足。"""
    月份 = sorted({e["ts"][:7] for e in 条目们})
    有产出 = any(e["level"] >= 2 or e["anchors"]["link"] for e in 条目们)

    条件 = {
        "重复": len(月份) >= 2,          # 同一主题在 ≥2 个不同月份出现
        "产出": 有产出,                   # 有可验证的产出物
        "厚度": len(条目们) >= 3,         # 至少 3 条独立 entry
    }
    缺 = [
        说明
        for 名, 说明 in (
            ("重复", "只在 1 个月里出现过（要跨 ≥2 个月）"),
            ("产出", "没有可验证的产出物（repo / 链接 / 通过测试）"),
            ("厚度", f"只有 {len(条目们)} 条记录（要 ≥3 条）"),
        )
        if not 条件[名]
    ]
    条件["全满足"] = all(条件[名] for 名 in ("重复", "产出", "厚度"))
    条件["缺"] = 缺
    条件["月份"] = 月份
    return 条件


def _依据文字(记录: dict) -> str:
    """changelog 里那行「依据」。照 DESIGN.md §3.2 的示例写法。"""
    月份 = "、".join(m[5:].lstrip("0") + " 月" for m in 记录["月份"])
    部分 = [f"跨 {月份}", f"共 {记录['条数']} 条记录"]
    if 记录.get("产出物"):
        部分.insert(1, 记录["产出物"])
    return "、".join(部分)


def _找主题(条目们: list[dict]) -> list[dict]:
    """让模型把这一批记录归纳成主题。"""
    系统提示 = config.prompt文件("settle.md").read_text(encoding="utf-8")
    用户内容 = "记录如下：\n\n" + "\n".join(
        f"- id={e['id']} 日期={e['ts'][:10]} 档位={e['level']}：{e['did']}"
        for e in 条目们
    )

    try:
        回复 = llm.调用("settle", 系统提示, 用户内容)
    except config.配置错误 as 错误:
        raise 晋升错误(f"固化需要模型，但现在调不了：\n{错误}") from 错误
    except llm.网络错误 as 错误:
        raise 晋升错误(f"连不上模型，这次没固化：\n{错误}") from 错误

    数据, 解析错误 = extract.解析模型回复(回复.文本)
    if 解析错误:
        raise 晋升错误(f"模型没给出能用的结果：{解析错误}")

    主题们 = 数据.get("themes")
    if not isinstance(主题们, list):
        raise 晋升错误("模型的结果里没有 themes 字段。")
    return 主题们


# ── 提名的存取 ───────────────────────────────────────────────


def 提名目录() -> Path:
    目录 = store.确保vault就绪() / "缓存" / "提名"
    目录.mkdir(parents=True, exist_ok=True)
    return 目录


def _提名文件(标题: str) -> Path:
    return 提名目录() / f"{store.清洗文件名(标题)}.json"


def _存提名(记录: dict) -> None:
    文件 = _提名文件(记录["标题"])
    内容 = {**记录, "状态": "待确认", "提出时间": store.时间文本(store.现在())}
    文件.write_text(json.dumps(内容, ensure_ascii=False, indent=2), encoding="utf-8")


def 待确认提名() -> list[dict]:
    """列出还没处理过的提名。"""
    结果 = []
    for 文件 in sorted(提名目录().glob("*.json")):
        try:
            数据 = json.loads(文件.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if 数据.get("状态") == "待确认":
            结果.append(数据)
    return 结果


def _被拒绝过的标题() -> set[str]:
    """拒绝过的主题以后不再提（DESIGN.md §4.6 的验收项）。"""
    结果: set[str] = set()
    for 文件 in 提名目录().glob("*.json"):
        try:
            数据 = json.loads(文件.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if 数据.get("状态") == "已拒绝":
            结果.add(str(数据.get("标题") or ""))
    return 结果


def _改提名状态(标题: str, 状态: str) -> None:
    文件 = _提名文件(标题)
    if not 文件.exists():
        raise 晋升错误(f"找不到提名「{标题}」。")
    数据 = json.loads(文件.read_text(encoding="utf-8"))
    数据["状态"] = 状态
    文件.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 确认 / 拒绝（life promote）───────────────────────────────


def 确认(标题: str) -> dict:
    """确认提名：建章节、把条目回填 chapter、写晋升日志。"""
    文件 = _提名文件(标题)
    if not 文件.exists():
        raise 晋升错误(f"找不到提名「{标题}」。")
    记录 = json.loads(文件.read_text(encoding="utf-8"))
    if 记录.get("状态") != "待确认":
        raise 晋升错误(f"这条提名已经处理过了（{记录.get('状态')}）。")

    连接 = index.连接索引()
    try:
        条目们 = [e for e in (index.取条目(连接, i) for i in 记录["条目ids"]) if e]
        if not 条目们:
            raise 晋升错误("这条提名底下的记录都找不到了，先跑 `life reindex`。")

        章节 = store.新建章节(
            title=记录["标题"],
            started=min(e["ts"][:10] for e in 条目们),
            entry_count=len(条目们),
            level_max=max(e["level"] for e in 条目们),
            last_evidence=max(e["ts"][:10] for e in 条目们),
            body=记录.get("摘要") or "",
        )
        store.写章节(章节)
        index.写入章节(连接, 章节)

        # 回填：每条记录的 chapter 字段指向这个章节（DESIGN.md §4.6 的验收项）
        for 条目 in 条目们:
            条目["chapter"] = 章节["id"]
            store.写条目(条目)
            index.写入条目(连接, 条目)
    finally:
        连接.close()

    _改提名状态(标题, "已晋升")
    store.追加日志(f"晋升 {标题}：当下 → 章节「{章节['id']}」")
    store.追加日志("依据：" + _依据文字(记录), 带日期=False)
    return {"章节": 章节, "回填": [e["id"] for e in 条目们]}


def 拒绝(标题: str) -> None:
    """拒绝提名。以后同一主题不再重复提。"""
    _改提名状态(标题, "已拒绝")
    store.追加日志(f"拒绝提名：{标题}（以后不再提这一条）")
