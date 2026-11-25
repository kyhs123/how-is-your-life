"""goal.py —— 人生规划：立目标、看证据（DESIGN.md §4.5）。

这个文件只做一件事：**把目标写成文件，并从记录里算出它现在的证据分布。**

刻意不做的事（设计里写死的禁止清单 §4.5）：
- 不做「完成百分比」——进度不是线性的，百分比是骗人的
- 不做 KPI 面板、不标红未完成、不催进度、不算连续天数
- 不替用户定目标，也不评判目标该不该有

所以整张卡片只有事实：多少条记录、每个证据档各几条、拿得出手的是什么。
"""

from __future__ import annotations

from datetime import timedelta

from life import index, store

档位名 = {0: "接触", 1: "复现", 2: "产出", 3: "能讲"}


class 目标错误(Exception):
    """目标层面的问题（找不到、重名之类）。"""


# ── 增删查 ───────────────────────────────────────────────────


def 建目标(
    标题: str,
    *,
    期限: str = "term",
    为什么: str = "",
    截止: str = "",
    上级: str = "",
) -> dict:
    """立一个目标。同名的会报错（免得两份一样的东西）。"""
    for 已有 in store.全部目标():
        if 已有["title"] == 标题:
            raise 目标错误(f"已经有一个叫「{标题}」的目标了。改个名字，或者用 `life goal show {已有['id']}` 看它。")

    目标 = store.新建目标(
        title=标题, horizon=期限, why=为什么, due=截止, parent=上级
    )
    store.写目标(目标)

    连接 = index.连接索引()
    try:
        index.写入目标(连接, 目标)
    finally:
        连接.close()
    return 目标


def 全部目标() -> list[dict]:
    return store.全部目标()


def 找目标(标识: str) -> dict:
    """按 id、标题、id 前缀，或者列表里的序号找。

    序号是为了让你少打字：`life goal show 1` 就行。
    """
    标识 = (标识 or "").strip()
    目标们 = store.全部目标()

    if 标识.isdigit():
        序号 = int(标识)
        if 1 <= 序号 <= len(目标们):
            return 目标们[序号 - 1]
        raise 目标错误(f"没有第 {序号} 个目标。跑 `life goal list` 看有哪些。")

    for 目标 in 目标们:
        if 标识 in (目标["id"], 目标["title"]):
            return 目标

    前缀命中 = [t for t in 目标们 if t["id"].startswith(标识) or t["title"].startswith(标识)]
    if len(前缀命中) == 1:
        return 前缀命中[0]
    if len(前缀命中) > 1:
        raise 目标错误(
            "有多个目标都以这几个字开头，我不确定你说哪个：\n  "
            + "\n  ".join(t["title"] for t in 前缀命中)
        )
    raise 目标错误(f"没有找到目标「{标识}」。跑 `life goal list` 看有哪些。")


def 改状态(标识: str, 新状态: str, *, 原因: str = "") -> dict:
    目标 = 找目标(标识)
    if 新状态 not in store.目标状态取值:
        raise 目标错误(f"状态只能是 {list(store.目标状态取值)}。")

    目标 = {**目标, "status": 新状态}
    if 原因:
        目标["body"] = (目标.get("body") or "").rstrip() + f"\n（{新状态}：{原因}）\n"
    store.写目标(目标)

    连接 = index.连接索引()
    try:
        index.写入目标(连接, 目标)
    finally:
        连接.close()
    return 目标


# ── 证据（§4.5 的「进度展示用证据视图」）─────────────────────


def 关联条目(目标: dict) -> list[dict]:
    """哪些记录算在这个目标名下。

    依据是记录里的 `goal` 字段（抽取时模型填的）。所以「没关联上」通常是两个原因：
    抽取时没识别出目标，或者目标建好之前就记过了。
    """
    连接 = index.连接索引()
    try:
        行们 = 连接.execute(
            "SELECT id FROM entries WHERE private = 0 ORDER BY ts"
        ).fetchall()
        条目们 = [e for e in (index.取条目(连接, 行["id"]) for 行 in 行们) if e]
    finally:
        连接.close()

    标题 = 目标["title"]
    return [
        e
        for e in 条目们
        if e["goal"] and (标题 in e["goal"] or e["goal"] in 标题 or e["goal"] == 目标["id"])
    ]


def 算证据(目标: dict) -> dict:
    """数出来，不猜。"""
    条目们 = 关联条目(目标)
    档 = {档位: [] for 档位 in (0, 1, 2, 3)}
    for 条目 in 条目们:
        档.setdefault(条目["level"], []).append(条目)

    分钟 = sum(e["minutes"] for e in 条目们)
    最近 = max((e["ts"][:10] for e in 条目们), default="")
    三天前 = (store.现在() - timedelta(days=3)).date().isoformat()

    return {
        "条数": len(条目们),
        "分钟": 分钟,
        "档": 档,
        "最近": 最近,
        "最近三天有记录": bool(最近) and 最近 >= 三天前,
        "条目们": 条目们,
    }


def 渲染卡片(目标: dict, 统计: dict | None = None) -> str:
    """一张证据卡。照 DESIGN.md §4.5 的样子来，但只写真有的东西。"""
    统计 = 统计 or 算证据(目标)

    开头 = 目标["started"][:7] if 目标["started"] else "?"
    结尾 = "现在" if 目标["status"] == "active" else {
        "done": "已完成",
        "stopped": "已停",
        "paused": "暂停中",
    }.get(目标["status"], 目标["status"])

    行 = [f"## {目标['title']}    {开头} → {结尾}"]

    摘要 = [f"{统计['条数']} 条记录"]
    if 统计["分钟"]:
        摘要.append(f"投入 ~{统计['分钟'] / 60:.0f}h")
    if 统计["最近三天有记录"]:
        摘要.append("最近 3 天活跃")
    行.append(" ｜ ".join(摘要))

    if not 统计["条数"]:
        行.append("")
        行.append("  这个目标还没挂上任何记录。")
        行.append("  （记录里的 goal 字段要和目标标题对上，才算它的证据。）")
        return "\n".join(行)

    行.append("")
    行.append("证据分布")
    for 档位 in (3, 2, 1, 0):
        条目们 = 统计["档"].get(档位) or []
        if not 条目们:
            continue
        举例 = "、".join(e["did"][:24] for e in 条目们[:3])
        行.append(f"  {档位名[档位]}    {len(条目们):>2} 条   {举例}")

    能拿出手 = [e for e in 统计["条目们"] if e["level"] >= 2]
    行.append("")
    if 能拿出手:
        行.append("能拿出手的：")
        for 条目 in sorted(能拿出手, key=lambda e: (-e["level"], e["ts"]))[:5]:
            行.append(f"  · {条目['did']}（{档位名[条目['level']]}）")
    else:
        行.append("能拿出手的：还没有产出或能讲级别的记录。")

    缺什么 = []
    if not 能拿出手:
        缺什么.append("以接触为主，缺少独立产出")
    if not (统计["档"].get(3) or []):
        缺什么.append("还没有「能讲」级别的记录——也就是讲给别人听、或者在原场景之外用过")
    if 缺什么:
        行.append("")
        行.append("还缺：" + "；".join(缺什么))

    return "\n".join(行)


def 一行概览(序号: int, 目标: dict) -> str:
    """`life goal list` 用：一行一个，不刷屏。"""
    状态 = {"active": "进行中", "done": "已完成", "stopped": "已停", "paused": "暂停"}.get(
        目标["status"], 目标["status"]
    )
    期限 = {"short": "短", "term": "一学期", "long": "长期"}.get(目标["horizon"], 目标["horizon"])
    截止 = f"｜截止 {目标['due']}" if 目标["due"] else ""
    return f"{序号}. {目标['title']}    {状态}｜{期限}{截止}"
