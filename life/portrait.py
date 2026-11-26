"""portrait.py —— 季度画像（DESIGN.md §4.7 / §3.4 portrait）。

写的是**假设**，不是判决。

「我猜你在被否定时会先缩起来，而不是争辩。（依据：3 次类似场景）」
    ✅ 可以商量、可以推翻
「你是一个内向、缺乏自信的人。」
    ❌ 固定标签，必然滑向巴纳姆效应

另一条规矩：和上季度对比时，**被推翻的旧假设要留着（删除线）**。
「我上次猜错了」这件事本身就是信息，直接覆盖等于假装自己一直都对。
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from life import config, index, llm, store

季度名格式 = re.compile(r"^(\d{4})-Q([1-4])$")


class 画像错误(Exception):
    """画像流程里的问题。"""


def 当前季度(哪天: date | None = None) -> str:
    哪天 = 哪天 or store.现在().date()
    return f"{哪天.year}-Q{(哪天.month - 1) // 3 + 1}"


def 上一季度(季度: str) -> str:
    匹配 = 季度名格式.match(季度)
    if not 匹配:
        raise 画像错误(f"季度名看不懂：{季度}")
    年, 季 = int(匹配.group(1)), int(匹配.group(2))
    return f"{年 - 1}-Q4" if 季 == 1 else f"{年}-Q{季 - 1}"


def 画像路径(季度: str) -> "object":
    return store.确保vault就绪() / "portrait" / f"{季度}.md"


def 读画像(季度: str) -> str:
    路径 = 画像路径(季度)
    return 路径.read_text(encoding="utf-8") if 路径.exists() else ""


# ── 收集材料 ─────────────────────────────────────────────────


def 全部条目() -> list[dict]:
    连接 = index.连接索引()
    try:
        行们 = 连接.execute(
            "SELECT id FROM entries WHERE private = 0 ORDER BY ts"
        ).fetchall()
        return [e for e in (index.取条目(连接, 行["id"]) for 行 in 行们) if e]
    finally:
        连接.close()


def 情绪统计(条目们: list[dict]) -> dict:
    """情绪模式。只数出来的东西，不猜。"""
    带情绪 = [e for e in 条目们 if e["emotion"]["valence"] != 0]
    负 = [e for e in 带情绪 if e["emotion"]["valence"] <= -0.3]
    正 = [e for e in 带情绪 if e["emotion"]["valence"] >= 0.3]
    触发 = Counter(
        e["emotion"]["trigger"].strip()
        for e in 条目们
        if e["emotion"]["trigger"].strip()
    )
    按月: dict[str, list[float]] = {}
    for 条目 in 带情绪:
        按月.setdefault(条目["ts"][:7], []).append(条目["emotion"]["valence"])

    return {
        "有情绪的记录": len(带情绪),
        "负面": len(负),
        "正面": len(正),
        "最常见的触发": 触发.most_common(3),
        "按月平均": {月: round(sum(值) / len(值), 2) for 月, 值 in sorted(按月.items())},
    }


def _材料(季度: str, 条目们: list[dict], 上季: str) -> str:
    段: list[str] = []

    段.append(f"# 时间范围\n这是 {季度} 的画像。总共 {len(条目们)} 条记录。")

    底色 = store.读底色项()
    段.append("\n# 底色（长期是什么样的人）")
    段.append(
        "\n".join(f"- {项['name']}" for 项 in 底色) if 底色 else "（还没有底色）"
    )

    章节 = store.全部章节()
    段.append("\n# 活跃主题（这半年在做什么）")
    段.append(
        "\n".join(
            f"- {c['title']}：{c['entry_count']} 条记录，最高 {c['level_max']} 档"
            for c in 章节
        )
        if 章节
        else "（还没有主题）"
    )

    统计 = 情绪统计(条目们)
    段.append("\n# 情绪统计")
    段.append(
        f"- 带情绪的记录 {统计['有情绪的记录']} 条：负面 {统计['负面']} 条，正面 {统计['正面']} 条"
    )
    if 统计["最常见的触发"]:
        段.append(
            "- 最常见触发：" + "、".join(f"{词}（{次数} 次）" for 词, 次数 in 统计["最常见的触发"])
        )
    if 统计["按月平均"]:
        段.append(
            "- 按月平均情绪：" + "、".join(f"{月} {值:+.1f}" for 月, 值 in 统计["按月平均"].items())
        )

    上次 = 读画像(上季)
    段.append(f"\n# 上季度（{上季}）的画像")
    段.append(上次.strip() if 上次.strip() else "（这是第一份画像，没有上一季度。）")

    return "\n".join(段)


# ── 生成 ─────────────────────────────────────────────────────


def 生成(*, 季度: str | None = None) -> dict:
    """生成（或覆盖）本季度画像。返回 {"季度", "路径", "缺依据的假设": [...], "token": n}"""
    季度 = 季度 or 当前季度()
    条目们 = 全部条目()
    if not 条目们:
        raise 画像错误("还没有任何记录，画像无从谈起。先记几条再来。")

    上季 = 上一季度(季度)
    系统提示 = config.prompt文件("portrait.md").read_text(encoding="utf-8")
    用户内容 = _材料(季度, 条目们, 上季) + f"\n\n请写 {季度} 的画像。"

    try:
        回复 = llm.调用("settle", 系统提示, 用户内容, 要JSON=False)
    except config.配置错误 as 错误:
        raise 画像错误(f"画像需要模型，但现在调不了：\n{错误}") from 错误
    except llm.网络错误 as 错误:
        raise 画像错误(f"连不上模型，这次没生成：\n{错误}") from 错误

    正文 = 回复.文本.strip()
    if not 正文:
        raise 画像错误("模型返回了空内容（可能被要求输出 JSON 了）。这次不写文件，免得留一份空白画像。")
    路径 = 画像路径(季度)
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text(正文 + "\n", encoding="utf-8")

    return {
        "季度": 季度,
        "路径": 路径,
        "缺依据的假设": 缺依据的假设(正文),
        "token": 回复.输入token + 回复.输出token,
    }


def 缺依据的假设(正文: str) -> list[str]:
    """§4.7 的验收项：每条假设都要带「依据：N 次类似场景」。

    没有依据的假设，多半是模型在说场面话。不拦下它，但要指出来。
    """
    缺: list[str] = []
    在假设段 = False
    for 行 in 正文.splitlines():
        行 = 行.strip()
        if 行.startswith("###"):
            在假设段 = "假设" in 行
            continue
        if 在假设段 and 行.startswith("- ") and "依据" not in 行:
            缺.append(行[2:])
    return 缺


def 只看变化(季度: str | None = None) -> str:
    """`life portrait --diff`：只把「相对上季度的变化」那一块拿出来。"""
    季度 = 季度 or 当前季度()
    正文 = 读画像(季度)
    if not 正文.strip():
        raise 画像错误(f"{季度} 还没有画像。先跑 `life portrait`。")

    块: list[str] = []
    收集中 = False
    for 行 in 正文.splitlines():
        if 行.strip().startswith("###"):
            收集中 = "变化" in 行
            if 收集中:
                块.append(行)
            continue
        if 收集中:
            块.append(行)

    return "\n".join(块).strip() or "这一版画像里没有「变化」那一块。"
