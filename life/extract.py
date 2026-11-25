"""extract.py —— 抽取：把一段话变成 entry。

DESIGN.md §4.2 的全部要求都落在这个文件里：

- 结构化输出 + 三级降级     → 交给 life/llm.py，这里只管「解析出来的东西对不对」
- 客户端校验               → 校验条目()
- 校验失败重试一次，把错误回喂给模型 → 抽取() 里那个 for 循环
- 两次都失败标 needs_review，不静默丢弃 → 兜底条目()
- 缓存键 (content_hash, prompt_ver, model) → 缓存那一小节

这一层不碰数据库，也不写 markdown，只负责「产出干净的数据」。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from life import config, fake_model, index, llm, store

# 模型应该吐出来的字段结构。第 1 级降级（json_schema）会把它直接发给接口。
# 字段名必须和 DESIGN.md §3.4 一致，不然存下来的 markdown 就是错的。
抽取结构 = {
    "type": "object",
    "properties": {
        "ocr_text": {"type": "string"},
        "digest": {"type": "string"},
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "did": {"type": "string"},
                    "body": {"type": "string"},
                    "part": {"type": "string", "enum": list(store.记录部分)},
                    "minutes": {"type": "integer"},
                    "outcome": {"type": "string", "enum": list(store.结果取值)},
                    "anchors": {
                        "type": "object",
                        "properties": {
                            "tech": {"type": "array", "items": {"type": "string"}},
                            "people": {"type": "array", "items": {"type": "string"}},
                            "link": {"type": "string"},
                        },
                        "required": ["tech", "people", "link"],
                    },
                    "emotion": {
                        "type": "object",
                        "properties": {
                            "valence": {"type": "number"},
                            "arousal": {"type": "number"},
                            "trigger": {"type": "string"},
                            "quote": {"type": "string"},
                        },
                        "required": ["valence", "arousal", "trigger", "quote"],
                    },
                    "level": {"type": "integer"},
                    "goal": {"type": "string"},
                    "blockers": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "did",
                    "body",
                    "part",
                    "minutes",
                    "outcome",
                    "anchors",
                    "emotion",
                    "level",
                    "goal",
                    "blockers",
                ],
            },
        },
    },
    "required": ["entries"],
}

正文上限 = store.正文上限  # DESIGN.md §5.2 第 4 条（唯一定义在 store.py）


class 抽取错误(Exception):
    """抽取过程中没法继续的错误（配置错了、模型胡说八道之类）。"""


# ── 对外只有一个函数：抽取 ─────────────────────────────────────


def 抽取(
    原文: str,
    *,
    部分: str = "record",
    图片路径: Path | None = None,
    原文文件名: str = "",
    私密: bool = False,
    用假模型: bool = False,
    内容指纹: str = "",
    时间提示: str = "",
) -> dict:
    """把一次输入抽成一条或几条 entry 的**原始字段**（还没分配 id）。

    返回值：
        {
          "entries": [ {did/body/part/...}, ... ],   # 已经过校验和规范化
          "ocr_text": "...",                          # 只有图片才有内容
          "digest": "...",                            # 同上
          "status": "settled" | "needs_review",
          "备注": "给用户看的一句话说明",
          "prompt_ver": "...", "模型名": "...",        # 写缓存时要用
        }

    给了「内容指纹」的话，会先看缓存：同样的内容 + 同样的 prompt + 同样的模型，
    就不重复花钱了（DESIGN.md §4.2 的缓存键）。
    """
    # ① 先把「这次用的是哪份 prompt、哪个模型」算出来（缓存键要用）
    有图 = 图片路径 is not None
    prompt名 = "extract_image.md" if 有图 else "extract.md"
    版本 = prompt版本(prompt名)
    模型 = 当前模型名(用假模型)

    # ② private：DESIGN.md §8 规定这条绝不能发给任何接口
    if 私密:
        兜底 = _本地兜底(
            原文, 部分, 备注="这条标了 private，按设计完全不发给任何接口，只做本地截断。"
        )
        兜底["prompt_ver"] = 版本
        兜底["模型名"] = 模型
        return 兜底

    # ③ 先看缓存（同样的内容 + 同样的 prompt + 同样的模型 → 不再花一次钱）
    if 内容指纹:
        命中 = 取缓存结果(读缓存(内容指纹), 版本, 模型)
        if 命中:
            return {**命中, "prompt_ver": 版本, "模型名": 模型, "命中缓存": True}

    系统提示 = config.prompt文件(prompt名).read_text(encoding="utf-8")
    用户内容 = _组装用户内容(原文, 部分, 有图=有图, 时间提示=时间提示)

    # ④ 空输入不调模型。
    # 真模型被喂了空字符串时会「礼貌地」编一条出来（实测编过一条网络配置记录），
    # 宁可不花这个钱，也不往你的记录里塞假东西。
    if not 原文.strip() and not 有图:
        return {
            "entries": [],
            "ocr_text": "",
            "digest": "",
            "status": "needs_review",
            "备注": "输入是空的，没有调用模型（免得它凭空编一条记录）。",
            "prompt_ver": 版本,
            "模型名": 模型,
        }

    # ⑤ 拿数据：假模型 or 真模型
    数据 = None
    上次错误: list[str] = []
    for _ in (1, 2):
        内容 = 用户内容
        if 上次错误:
            内容 += (
                "\n\n上一次你返回的结果有问题，请改正后重新输出完整的 JSON：\n- "
                + "\n- ".join(上次错误)
            )

        原始文本 = _调一次(用假模型, 有图, 原文文件名, 原文, 部分, 系统提示, 内容, 图片路径)
        数据, 解析错误 = _解析(原始文本)

        if 解析错误:
            上次错误 = [解析错误]
            continue

        上次错误 = 校验全部(数据)
        if not 上次错误:
            break
        if 用假模型:
            break  # 假模型不会因为被骂一句就变聪明，别浪费一轮

    # ⑦ 两次都不行 → 兜底，标 needs_review，不丢
    if 数据 is None or 上次错误:
        兜底 = _本地兜底(
            原文,
            部分,
            备注="模型两次都没给出合格结果，已按原话截断保存，标记 needs_review 等你来看。",
        )
        兜底["校验问题"] = 上次错误
        兜底["prompt_ver"] = 版本
        兜底["模型名"] = 模型
        return 兜底

    # ⑧ 规范化：补默认值、砍长度、夹范围
    条目们 = [_规整(一条, 部分) for 一条 in 数据.get("entries") or []]

    # ⑨ 模型说「这段没什么可记的」→ 按原话存，但**不打扰你**
    #
    # 为什么不是 needs_review：模型觉得「不值得记」不代表你说的话没价值。
    # 「今天过得很好」这种句子它经常判成空，却正是你想留下的东西。
    # needs_review 应该只留给「我们真的没抽出结构」的情况（见上面的兜底）。
    if not 条目们 and 原文.strip():
        兜底 = _本地兜底(
            原文,
            部分,
            备注="模型认为这段内容里没有可记录的事，我按你的原话存了一条（没打扰你确认）。",
        )
        兜底["status"] = "settled"
        兜底["prompt_ver"] = 版本
        兜底["模型名"] = 模型
        return 兜底

    结果 = {
        "entries": 条目们,
        "ocr_text": str(数据.get("ocr_text") or ""),
        "digest": str(数据.get("digest") or ""),
        "status": "settled",
        "备注": "",
        "prompt_ver": 版本,
        "模型名": 模型,
    }
    if not 条目们:
        结果["status"] = "needs_review"
        结果["备注"] = "这段内容里没有识别出可以记录的事。"
    return 结果


# ── 调模型 / 假模型 ──────────────────────────────────────────


def _调一次(
    用假模型: bool,
    有图: bool,
    原文文件名: str,
    原文: str,
    部分: str,
    系统提示: str,
    用户内容: str,
    图片路径: Path | None,
) -> str:
    """调一次，把「回复的原始文本」交回去。解析在 _解析 里做。"""
    if 用假模型:
        假结果 = fake_model.假看图(原文文件名, 原文) if 有图 else fake_model.假抽取(原文, 部分)
        return json.dumps(假结果, ensure_ascii=False)

    回复 = llm.调用(
        "extract", 系统提示, 用户内容, 结构=抽取结构, 图片路径=图片路径
    )
    _记一笔账(回复)
    return 回复.文本


def _记一笔账(回复: llm.模型回复) -> None:
    """把这次调用的 token 数写进 usage 表（DESIGN.md §6.3）。"""
    连接 = index.连接索引()
    try:
        index.记录用量(连接, "extract", 回复.模型名, 回复.输入token, 回复.输出token)
    finally:
        连接.close()


def _组装用户内容(原文: str, 部分: str, *, 有图: bool, 时间提示: str = "") -> str:
    """把用户原话和一点提示拼成发给模型的内容。"""
    片段 = []
    if 时间提示.strip():
        片段.append(时间提示.strip())
    if 原文.strip():
        片段.append(原文.strip())
    elif 有图:
        片段.append("（用户只发了图，没打字。）")

    if 部分 == "emotion":
        片段.append("（这条是情感记录：part 必须是 emotion，level 固定 0。）")
    elif 部分 == "plan":
        片段.append("（这条是规划记录：part 必须是 plan。）")
    return "\n\n".join(片段)


# ── 解析：从模型回复里拿到一个字典 ────────────────────────────


def 解析模型回复(文本: str) -> tuple[dict | None, str]:
    """对外的名字：别的模块（比如晋升）也要解析模型回复，就直接用这个。"""
    return _解析(文本)


def _解析(文本: str) -> tuple[dict | None, str]:
    """把模型回复变成字典。

    正常情况直接 json.loads 就成。
    但模型有时候会把 JSON 包在 ```json 代码块里，或者前面写一句「好的，结果如下」——
    这就是 DESIGN.md §4.2 说的第 3 级情况，这里负责把那段 JSON 抠出来。
    """
    if not 文本 or not 文本.strip():
        return None, "回复是空的。"

    原文 = 文本.strip()

    # 情况一：整段就是 JSON
    try:
        数据 = json.loads(原文)
        if isinstance(数据, dict):
            return 数据, ""
        if isinstance(数据, list):
            return {"entries": 数据}, ""
        return None, "回复不是 JSON 对象。"
    except json.JSONDecodeError:
        pass

    # 情况二：包在代码块里
    代码块 = re.search(r"```(?:json)?\s*(.+?)\s*```", 原文, re.S)
    if 代码块:
        try:
            数据 = json.loads(代码块.group(1))
            return ({"entries": 数据} if isinstance(数据, list) else 数据), ""
        except json.JSONDecodeError:
            pass

    # 情况三：前后有废话，从第一个 { 到最后一个 } 抠
    头 = 原文.find("{")
    尾 = 原文.rfind("}")
    if 头 != -1 and 尾 > 头:
        try:
            数据 = json.loads(原文[头 : 尾 + 1])
            if isinstance(数据, dict):
                return 数据, ""
        except json.JSONDecodeError:
            pass

    return None, f"回复里找不到能解析的 JSON。前 200 个字是：{原文[:200]}"


# ── 校验与规范化 ─────────────────────────────────────────────


def 校验全部(数据: dict) -> list[str]:
    """检查模型给的东西能不能用。返回一串中文错误，空列表 = 没问题。"""
    条目们 = 数据.get("entries")
    if 条目们 is None:
        return ["回复里没有 entries 字段。"]
    if not isinstance(条目们, list):
        return ["entries 必须是数组。"]

    全部错误: list[str] = []
    for 序号, 一条 in enumerate(条目们, start=1):
        错误 = 校验条目(一条)
        全部错误.extend(f"第 {序号} 条：{错}" for 错 in 错误)
    return 全部错误


def 校验条目(候选: object) -> list[str]:
    """单条 entry 的检查。只拦「真的不能用」的问题，别的都在 _规整 里修。"""
    if not isinstance(候选, dict):
        return ["这条不是一个键值对象。"]

    错误: list[str] = []

    句子 = str(候选.get("did") or "").strip()
    if not 句子:
        错误.append("did 是空的。")
    elif len(句子) > 正文上限:
        错误.append(f"did 有 {len(句子)} 个字，超过 {正文上限} 字上限。")

    部分 = 候选.get("part")
    if 部分 not in store.记录部分:
        错误.append(f"part 只能是 {list(store.记录部分)} 之一，你给的是 {部分!r}。")

    锚点 = 候选.get("anchors") or {}
    if 部分 == "record" and not (
        (锚点.get("tech") or []) or (锚点.get("people") or []) or (锚点.get("link") or "")
    ):
        错误.append(
            "part 是 record，但一个锚点都没有。"
            "请把技术名、数字、报错原文、链接或人名留在 anchors 里。"
        )

    return 错误


def _规整(候选: dict, 部分: str) -> dict:
    """把模型给的零碎数据收拾成统一形状（缺的补默认、超范围的夹回去）。"""
    情绪 = 候选.get("emotion") or {}
    锚点 = 候选.get("anchors") or {}

    句子 = str(候选.get("did") or "").strip()[:正文上限]
    正文 = str(候选.get("body") or "").strip()[:正文上限] or 句子

    指定 = 候选.get("part") if 候选.get("part") in store.记录部分 else 部分
    if 部分 != "record":
        指定 = 部分  # 用户用 --emotion 明说的，以用户为准

    结果 = 候选.get("outcome")
    if 结果 not in store.结果取值:
        结果 = "done"

    return {
        "did": 句子,
        "body": 正文,
        "part": 指定,
        "minutes": max(0, int(候选.get("minutes") or 0)),
        "outcome": 结果,
        "anchors": {
            "tech": [str(x) for x in (锚点.get("tech") or [])],
            "people": [str(x) for x in (锚点.get("people") or [])],
            "link": str(锚点.get("link") or ""),
        },
        "emotion": {
            "valence": _夹(情绪.get("valence"), -1.0, 1.0),
            "arousal": _夹(情绪.get("arousal"), 0.0, 1.0),
            "trigger": str(情绪.get("trigger") or ""),
            "quote": str(情绪.get("quote") or ""),
        },
        "level": min(3, max(0, int(候选.get("level") or 0))),
        "goal": str(候选.get("goal") or ""),
        "blockers": [str(x) for x in (候选.get("blockers") or [])],
    }


def _夹(值: object, 最小: float, 最大: float) -> float:
    """把一个数字夹在区间里。模型经常给个 1.5 或者干脆给空。"""
    try:
        数字 = float(值)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return min(最大, max(最小, 数字))


def _本地兜底(原文: str, 部分: str, *, 备注: str) -> dict:
    """不调模型的保底处理：把原话截断保存，标 needs_review。

    为什么要兜底而不是报错退出：DESIGN.md C5 和 §4.2 都要求「不静默丢弃」。
    用户写下来的东西，哪怕抽不好，也必须留在磁盘上。
    """
    句子 = " ".join(原文.split())[:正文上限] or "（空输入）"
    return {
        "entries": [
            {
                "did": 句子,
                "body": " ".join(原文.split())[:正文上限] or "（空输入）",
                "part": 部分,
                "minutes": 0,
                "outcome": "done",
                "anchors": {"tech": [], "people": [], "link": ""},
                "emotion": {"valence": 0.0, "arousal": 0.0, "trigger": "", "quote": ""},
                "level": 0,
                "goal": "",
                "blockers": [],
            }
        ],
        "ocr_text": "",
        "digest": "",
        "status": "needs_review",
        "备注": 备注,
    }


# ── 缓存（也用来防重复提交）────────────────────────────────────


def prompt版本(prompt文件名: str) -> str:
    """prompt 的「版本号」= 它内容的指纹。

    这样你改了 prompt，缓存自动失效，不用记得手动改版本号（DESIGN.md §4.2 的 prompt_ver）。
    """
    内容 = config.prompt文件(prompt文件名).read_text(encoding="utf-8")
    return hashlib.sha256(内容.encode("utf-8")).hexdigest()[:8]


def 当前模型名(用假模型: bool) -> str:
    """这次用的是哪个模型。缓存键要用它——换了模型就该重新抽一遍。"""
    if 用假模型:
        return "假模型"
    任务 = config.读取任务("extract")
    return str(getattr(任务, "model", "") or "未配置")


def 缓存目录() -> Path:
    目录 = store.确保vault就绪() / "缓存" / "抽取"
    目录.mkdir(parents=True, exist_ok=True)
    return 目录


def 缓存路径(指纹: str) -> Path:
    """缓存文件放哪：按指纹前两位分桶。

    为什么分桶：每条内容一个文件，五年下来九千个，全堆在一个目录里
    Windows 列目录会卡、查找也慢。分成 256 个桶，单目录最多几十个。
    """
    return 缓存目录() / 指纹[:2] / f"{指纹}.json"


def 读缓存(指纹: str) -> dict | None:
    """按内容指纹把整个缓存文件读出来（含防重复用的 entry_paths）。

    兼容老版本：以前是扁平存的（``缓存/抽取/<指纹>.json``），第一次读到
    就顺手搬进桶里，不用单独跑迁移。
    """
    路径 = 缓存路径(指纹)
    if not 路径.exists():
        旧路径 = 缓存目录() / f"{指纹}.json"
        if not 旧路径.exists():
            return None
        路径.parent.mkdir(parents=True, exist_ok=True)
        旧路径.replace(路径)
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None  # 缓存坏了就当没有，不影响你的数据


def 取缓存结果(缓存文件: dict | None, 版本: str, 模型: str) -> dict | None:
    """从缓存里取出「同一份 prompt + 同一个模型」抽过的结果。

    DESIGN.md §4.2 的缓存键是 (content_hash, prompt_ver, model)：
    内容指纹在文件名上，prompt 版本和模型名拼成这一格的钥匙。
    """
    if not 缓存文件:
        return None
    结果表 = 缓存文件.get("结果表") or {}
    return 结果表.get(f"{版本}|{模型}")


def 写缓存(指纹: str, 结果: dict, 记录路径们: list[Path]) -> None:
    """把这次抽取的结果和「指纹 → 记录文件」写进缓存。

    同一个指纹只留一个文件：换 prompt 或换模型时是往里加一格，不是覆盖掉旧的。
    """
    vault = config.vault目录()
    旧 = 读缓存(指纹) or {}
    结果表 = dict(旧.get("结果表") or {})
    结果表[f"{结果.get('prompt_ver') or '?'}|{结果.get('模型名') or '?'}"] = {
        "entries": 结果.get("entries") or [],
        "ocr_text": 结果.get("ocr_text") or "",
        "digest": 结果.get("digest") or "",
        "status": 结果.get("status") or "settled",
        "备注": 结果.get("备注") or "",
    }

    内容 = {
        "内容指纹": 指纹,
        "entry_paths": [
            str(p.relative_to(vault)).replace("\\", "/") for p in 记录路径们
        ],
        "结果表": 结果表,
    }

    路径 = 缓存路径(指纹)
    路径.parent.mkdir(parents=True, exist_ok=True)
    临时 = 路径.with_name(路径.name + ".tmp")
    临时.write_text(json.dumps(内容, ensure_ascii=False, indent=2), encoding="utf-8")
    临时.replace(路径)
