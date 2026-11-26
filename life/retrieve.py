"""retrieve.py —— 三路检索（DESIGN.md §4.3）。

三路各管一件事，谁也替不了谁：

    路 1 向量     「找意思相近的」——你说「我好累」，它能找到「撑不住了」那条
    路 2 全文+实体 「找特定的词」——你说「张三」，它找到所有提到张三的
    路 3 结构     「按时间和情绪找」——你问「上次这么难受是什么时候」，
                  它走 SQL，不靠文字相似

第 3 路最容易被忽略，但它才是这个产品的关键：人崩溃时想问的往往不是「搜索」，
而是「我以前也这样过吗，后来怎么好的」。

合并办法：三路各取 10 条，按名次算分（RRF），去重后取前 5~8 条。
私密记录在这里一律被过滤掉（§4.3 / §8）。
"""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import timedelta

from life import config, index, llm, store

# ── 结构检索的关键词表（第 3 路靠它决定走哪条 SQL）──────────────
#
# 这张表决定了「你说的话像不像在说情绪」。表里没有的说法就走不到情绪检索——
# 所以它宁可宽一点：多命中一次，最坏的结果是多翻出几条旧的低落记录；
# 少命中一次，用户就会觉得「它根本不懂我在说什么」。

情绪词 = (
    # 最直接的
    "累", "疲惫", "心累", "难受", "不舒服",
    # 崩掉的那些
    "崩溃", "撑不住", "扛不住", "喘不过气", "窒息", "熬不住", "顶不住",
    # 低落一类
    "低落", "沮丧", "消沉", "没劲", "提不起劲", "没意思", "空虚", "空落落",
    # 焦虑与害怕
    "焦虑", "害怕", "恐惧", "慌", "心慌", "紧张", "不安",
    # 憋着的那一类（这几种最常被说成「说不清」）
    "烦", "压抑", "郁闷", "窝火", "憋", "堵", "闷", "委屈", "生气",
    # 更重的
    "绝望", "无助", "迷茫", "孤独", "寂寞", "想哭", "想消失",
    # 自我否定
    "内疚", "自责", "羞愧", "没用", "废物",
    # 网络口语
    "emo", "破防", "麻了", "碎了", "躺平", "摆烂", "内耗", "社死",
)

恢复词 = (
    "恢复", "好起来", "走出来", "缓过来", "缓过劲", "怎么好", "怎么熬",
    "怎么撑", "撑过去", "后来", "变好", "回到正轨",
)

日期词 = ("今天", "去年", "一年前", "这个时候", "这时候", "那天", "那阵", "那会儿")

# 「我是什么样的人」这类问题，字面上和任何一条记录都不像。
# 它要的不是「相似」，而是「代表性」：把最能说明问题的记录挑出来。
元问题词 = (
    "什么样的人", "什么人", "我是谁", "我做过什么", "我会什么", "我擅长",
    "能力", "优点", "缺点", "评价我", "你觉得我", "介绍我", "经历",
)

每路条数 = 10  # §4.3：三路各取 10 条
时间路条数 = 30  # 「这周做了什么」这种问法，10 条不够：一周本来就可能记十几条


def 召回(
    查询: str, *, 取几条: int = 8, 用向量: bool = True
) -> tuple[list[dict], dict]:
    """给一个查询，返回（最相关的几条记录，诊断信息）。

    每条结果比普通条目多两个字段：
        ｜「来源」 这一条是被哪几路捞上来的（向量/全文/结构）
        ｜「分数」 合并后的分数，只用来排序，没有绝对意义
    """
    诊断: dict = {"查询": 查询, "各路": {}, "提示": [], "总数": 0}
    编号们: list[str] = []  # 向量路的结果，放外面以便下面统一合并

    连接 = index.连接索引()
    try:
        # ── 路 1：向量 ──
        if not 用向量:
            诊断["各路"]["向量"] = 0
            诊断["提示"].append("按你的要求跳过了向量路（--no-vectors）")
        else:
            能, 原因 = llm.能向量()
            if 能:
                编号们, 提示 = _向量路(连接, 查询)
                诊断["各路"]["向量"] = len(编号们)
                if 提示:
                    诊断["提示"].append(提示)
            else:
                编号们 = []
                诊断["各路"]["向量"] = 0
                诊断["提示"].append(f"向量路跳过：{原因}")

        # ── 路 2：全文 + 实体 ──
        全文编号, 全文提示 = _全文路(连接, 查询)
        诊断["各路"]["全文"] = len(全文编号)
        if 全文提示:
            诊断["提示"].append(全文提示)

        # ── 路 3：结构（时间与情绪）──
        结构编号, 结构说明 = _结构路(连接, 查询)
        诊断["各路"]["结构"] = len(结构编号)
        诊断["结构走了哪几条"] = 结构说明

        # ── 合并 ──
        # 问「这周做了什么」的时候，一周的记录本来就比 8 条多，
        # 只给 8 条会让它漏掉后面的事。这种问法放宽到时间路的上限。
        需要条数 = max(取几条, 时间路条数) if _时间段(查询) else 取几条
        结果 = _合并(连接, {"向量": 编号们, "全文": 全文编号, "结构": 结构编号}, 需要条数)
        诊断["总数"] = len(结果)
    finally:
        连接.close()

    return 结果, 诊断


# ── 路 1：向量相似 ───────────────────────────────────────────


def _向量路(连接: sqlite3.Connection, 查询: str) -> tuple[list[str], str]:
    """把查询也变成向量，跟库里所有向量算余弦相似度。"""
    向量表 = index.读全部向量(连接)
    if not 向量表:
        return [], "向量库是空的，先跑 `life reindex --vectors` 建一遍"

    try:
        查询向量们, _ = llm.嵌入([查询])
    except (llm.模型错误, llm.网络错误, config.配置错误) as 错误:
        return [], f"向量路失败（这次不影响其它两路）：{错误}"

    查询向量 = 查询向量们[0]

    # 私密记录不参与（§8）
    可见 = {
        行["id"]
        for 行 in 连接.execute("SELECT id FROM entries WHERE private = 0")
    }

    打分 = [
        (_余弦(查询向量, 向量), 编号)
        for 编号, 向量 in 向量表.items()
        if 编号 in 可见 and len(向量) == len(查询向量)
    ]
    打分.sort(reverse=True)
    return [编号 for 分, 编号 in 打分[:每路条数] if 分 > 0.2], ""


def _余弦(甲: list[float], 乙: list[float]) -> float:
    """两个向量的夹角余弦：1 = 完全同向，0 = 无关。"""
    if not 甲 or not 乙 or len(甲) != len(乙):
        return 0.0
    点积 = sum(a * b for a, b in zip(甲, 乙))
    甲长 = math.sqrt(sum(a * a for a in 甲))
    乙长 = math.sqrt(sum(b * b for b in 乙))
    if 甲长 == 0 or 乙长 == 0:
        return 0.0
    return 点积 / (甲长 * 乙长)


# ── 路 2：全文 + 实体 ───────────────────────────────────────


def _全文路(连接: sqlite3.Connection, 查询: str) -> tuple[list[str], str]:
    """FTS5 全文搜，外加 anchors（技术名/人名/链接）直接命中。

    关键一步：把整句话拆成片段分别搜。人不会只输入一个词——
    「OAuth 我好累」这种句子，整句拿去当短语匹配是匹配不到任何东西的。
    """
    查询 = 查询.strip()
    if not 查询:
        return [], ""

    片段们 = _片段们(查询)
    if not 片段们:
        return [], ""

    提示 = ""
    每段的编号: list[list[str]] = []

    for 片段 in 片段们:
        编号们: list[str] = []

        # ① 全文：trigram 分词要求至少 3 个字；更短就退回普通包含匹配
        if len(片段) >= 3:
            try:
                for 行 in 连接.execute(
                    "SELECT entry_id FROM entries_fts WHERE entries_fts MATCH ? "
                    "ORDER BY bm25(entries_fts) LIMIT ?",
                    (_fts查询式(片段), 每路条数),
                ):
                    编号们.append(行["entry_id"])
            except sqlite3.OperationalError as 错误:
                提示 = 提示 or f"全文检索这一步失败了，退回普通匹配：{错误}"

        if not 编号们:
            通配 = f"%{片段}%"
            for 行 in 连接.execute(
                "SELECT id FROM entries WHERE private = 0 AND (did LIKE ? OR body LIKE ?) "
                "ORDER BY ts DESC LIMIT ?",
                (通配, 通配, 每路条数),
            ):
                编号们.append(行["id"])
            if len(片段) < 3 and not 提示:
                提示 = "有片段不到 3 个字，全文索引（trigram）用不上，改成了简单的包含匹配"

        # ② 实体：直接在锚点里找。人名/技术名往往就是这么被问起的
        if len(片段) >= 2:
            try:
                for 行 in 连接.execute(
                    "SELECT id FROM entries WHERE private = 0 AND anchors LIKE ? "
                    "ORDER BY ts DESC LIMIT ?",
                    (f"%{片段}%", 每路条数),
                ):
                    编号们.append(行["id"])
            except sqlite3.OperationalError:
                pass

        每段的编号.append(list(dict.fromkeys(编号们)))

    # 轮流取：各片段的名次交替排列，免得某一个片段把名额占满
    合并: list[str] = []
    最长 = max((len(x) for x in 每段的编号), default=0)
    for 名次 in range(最长):
        for 一段 in 每段的编号:
            if 名次 < len(一段):
                合并.append(一段[名次])

    # 整句话提问又一条都没命中时，说清楚为什么（别让用户以为搜坏了）
    if not 合并 and len(查询) > 12:
        提示 = (提示 + "；" if 提示 else "") + (
            "全文路适合问「人名 / 技术名 / 项目名」，整句提问主要靠向量路（现在没配）"
        )

    return 合并, 提示


def _片段们(查询: str) -> list[str]:
    """把一句话拆成几个「可能被人当关键词问」的片段。

    「OAuth 我好累」→ ["OAuth", "我好累"]
    「上次那个 meta.roles 怎么弄的」→ ["meta.roles", "上次那个", "怎么弄的"]
    """
    import re

    片段: list[str] = []

    # 英文/数字串：技术名、报错词、版本号
    片段.extend(re.findall(r"[A-Za-z][A-Za-z0-9_+#.]{1,30}", 查询))

    # 中文：按标点和空格切开，两字以上才算
    for 块 in re.split(r"[\s，。、；：！？,.;:!?~]+", 查询):
        块 = 块.strip()
        if len(块) >= 2:
            片段.append(块)

    # 去重保序，最多 5 个（再多就变成噪音了）
    return list(dict.fromkeys(片段))[:5]


def _fts查询式(查询: str) -> str:
    """把用户输入变成 FTS5 的短语查询，顺便挡住它自己的语法符号（AND/OR/NEAR/-）。"""
    return '"' + 查询.replace('"', '""') + '"'


# ── 路 3：结构（时间与情绪）──────────────────────────────────


_中文数字 = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _数字(文本: str) -> int:
    """「3」和「三」都认。只认一位数和十，够用了。"""
    if 文本.isdigit():
        return int(文本)
    if 文本 == "十":
        return 10
    return _中文数字.get(文本, 0)


def _时间段(查询: str) -> tuple[str, str, str] | None:
    """认出「今天 / 昨天 / 这周 / 上周 / 这个月 / 上个月 / 最近三天」这类说法。

    返回（起, 止, 说明），起止是 2026-11-26 这种字符串；认不出返回 None。

    为什么要有这一路：用户问「我这周都做了什么」时，字面上和任何一条记录都不像
    （记录里没人写「这周」），三路全空，最后只能兜底给最近三条——那不叫回答。
    时间是最容易被忽略的一种「查询条件」。
    """
    今天 = store.现在().date()

    if "今天" in 查询:
        return 今天.isoformat(), 今天.isoformat(), "今天的记录"
    if "昨天" in 查询:
        昨天 = 今天 - timedelta(days=1)
        return 昨天.isoformat(), 昨天.isoformat(), "昨天的记录"

    if any(词 in 查询 for 词 in ("这周", "本周", "这星期", "这个星期", "最近一周")):
        周一 = 今天 - timedelta(days=今天.weekday())
        return 周一.isoformat(), 今天.isoformat(), "这周（从周一算起）的记录"
    if any(词 in 查询 for 词 in ("上周", "上个星期", "上一周", "上星期")):
        周一 = 今天 - timedelta(days=今天.weekday() + 7)
        return 周一.isoformat(), (周一 + timedelta(days=6)).isoformat(), "上周的记录"

    if any(词 in 查询 for 词 in ("这个月", "本月", "这一个月")):
        return 今天.replace(day=1).isoformat(), 今天.isoformat(), "这个月的记录"
    if any(词 in 查询 for 词 in ("上个月", "上月")):
        上月末 = 今天.replace(day=1) - timedelta(days=1)
        return 上月末.replace(day=1).isoformat(), 上月末.isoformat(), "上个月的记录"

    匹配 = re.search(r"最近\s*([0-9一二两三四五六七八九十]+)\s*(天|日|个?星期|个?周)", 查询)
    if 匹配:
        几 = _数字(匹配.group(1))
        if 几 > 0:
            起 = 今天 - timedelta(days=几 - 1)
            return 起.isoformat(), 今天.isoformat(), f"最近 {几} 天的记录"

    return None


def _结构路(连接: sqlite3.Connection, 查询: str) -> tuple[list[str], list[str]]:
    """按 DESIGN.md §4.3 里那三条 SQL 走。返回（编号们，走了哪几条的说明）。"""
    编号们: list[str] = []
    走了: list[str] = []

    # ⓪ 「这周 / 上周 / 最近三天」——按时间捞，不管字面像不像
    时段 = _时间段(查询)
    if 时段:
        起, 止, 说明 = 时段
        走了.append(说明)
        # 补记的旧事（when = 「大学期间」这种）不算进这个窗口：
        # 它们的 ts 是「补记那天」，拿来看「这周做了什么」会把整份简历都算成这周。
        # 只有 when 本身就是完整日期、且落在窗口里的，才跟着算。
        for 行 in 连接.execute(
            "SELECT id FROM entries WHERE private = 0 "
            "AND substr(ts, 1, 10) BETWEEN ? AND ? "
            'AND ("when" IS NULL OR "when" = \'\' OR ('
            "  \"when\" GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' "
            '  AND substr("when", 1, 10) BETWEEN ? AND ?)) '
            "ORDER BY ts DESC LIMIT ?",
            (起, 止, 起, 止, 时间路条数),
        ):
            编号们.append(行["id"])

    # ① 上次说类似的话是什么时候（情绪极点倒序）
    if any(词 in 查询 for 词 in 情绪词):
        走了.append("情绪极点")
        编号们 += _查(
            连接,
            "SELECT id FROM entries WHERE private = 0 AND valence < -0.5 "
            "ORDER BY ts DESC LIMIT ?",
        )

    # ② 去年今天
    if any(词 in 查询 for 词 in 日期词):
        走了.append("去年这个日子")
        今天 = store.现在()
        去年 = str(今天.year - 1)
        for 行 in 连接.execute(
            "SELECT id FROM entries WHERE private = 0 "
            "AND substr(ts, 6, 5) = ? AND substr(ts, 1, 4) = ? LIMIT ?",
            (今天.strftime("%m-%d"), 去年, 每路条数),
        ):
            编号们.append(行["id"])

    # ②.5 「我是什么样的人」→ 挑最能代表的，而不是最先想到的
    if any(词 in 查询 for 词 in 元问题词):
        走了.append("代表性记录（档位高的优先）")
        编号们 += _代表性(连接)

    # ③ 那次之后怎么恢复的（低谷之后的第一个 done）
    if any(词 in 查询 for 词 in 恢复词):
        走了.append("低谷之后怎么恢复")
        低谷 = 连接.execute(
            "SELECT ts FROM entries WHERE private = 0 AND valence < -0.5 "
            "ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if 低谷:
            for 行 in 连接.execute(
                "SELECT id FROM entries WHERE private = 0 AND ts > ? AND outcome = 'done' "
                "ORDER BY ts LIMIT 3",
                (低谷["ts"],),
            ):
                编号们.append(行["id"])

    return 编号们, 走了


def _代表性(连接: sqlite3.Connection, 条数: int = 12) -> list[str]:
    """挑「最能代表这个人」的记录：档位高的优先，同档按时间倒序。

    为什么需要这一路：用户问「你觉得我是个什么样的人」时，三路文字检索全是 0 命中，
    兜底只能给最近三条——那三条可能全是今天的琐事，简历里的项目一条都进不来。
    """
    行们 = 连接.execute(
        "SELECT id FROM entries WHERE private = 0 ORDER BY level DESC, ts DESC LIMIT ?",
        (条数,),
    ).fetchall()
    return [行["id"] for 行 in 行们]


def _查(连接: sqlite3.Connection, sql: str) -> list[str]:
    return [行["id"] for 行 in 连接.execute(sql, (每路条数,))]


# ── 合并 ─────────────────────────────────────────────────────


def _合并(
    连接: sqlite3.Connection, 各路: dict[str, list[str]], 取几条: int
) -> list[dict]:
    """RRF（倒数名次融合）：被多路同时捞到的排前面。

    没配 rerank 接口时这就是精排。配了也可以再加一层，但先别过度设计——
    DESIGN.md §4.3 说「rerank 取前 5~8 条」，RRF 已经能把这 5~8 条排对。
    """
    分数: dict[str, float] = {}
    来源: dict[str, list[str]] = {}

    for 名字, 编号们 in 各路.items():
        for 名次, 编号 in enumerate(dict.fromkeys(编号们), start=1):  # 去掉本路重复
            分数[编号] = 分数.get(编号, 0.0) + 1.0 / (60 + 名次)
            来源.setdefault(编号, []).append(名字)

    # 三路一条都没捞到：至少给最近 3 条，让对话有上下文可用
    if not 分数:
        for 行 in 连接.execute(
            "SELECT id FROM entries WHERE private = 0 ORDER BY ts DESC LIMIT 3"
        ):
            分数[行["id"]] = 0.0
            来源[行["id"]] = ["最近"]

    结果: list[dict] = []
    for 编号, 分 in sorted(分数.items(), key=lambda 对: 对[1], reverse=True)[:取几条]:
        条目 = index.取条目(连接, 编号)
        if 条目 is None or 条目["private"]:  # 再挡一次私密（§8）
            continue
        条目["来源"] = 来源.get(编号, [])
        条目["分数"] = round(分, 4)
        结果.append(条目)
    return 结果


# ── 给对话用的「最近几天」────────────────────────────────────


def 最近几天(天数: int = 3) -> list[dict]:
    """最近 N 天的记录（§4.4 的上下文里最后一块）。"""
    连接 = index.连接索引()
    try:
        最早 = (store.现在() - timedelta(days=天数)).date().isoformat()
        行们 = 连接.execute(
            "SELECT id FROM entries WHERE private = 0 AND substr(ts, 1, 10) >= ? "
            "ORDER BY ts DESC LIMIT 50",
            (最早,),
        ).fetchall()
        return [e for e in (index.取条目(连接, 行["id"]) for 行 in 行们) if e]
    finally:
        连接.close()
