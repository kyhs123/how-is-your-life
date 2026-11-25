"""fake_model.py —— 假模型。

**它不联网、不花钱、也不聪明。** 它只是一堆 if 规则，用来：

1. 你还没配密钥的时候，也能看清「输入 → 抽取 → 写文件 → 建索引」整条链路长什么样；
2. 自动测试的时候不依赖网络（测试要快、要稳定，不能每次都去调真接口）。

用法：`life add "..." --demo`

真用起来以后就别加 --demo 了，那时候走的是 life/llm.py 里的真接口。
"""

from __future__ import annotations

import re

# 一小撮常见技术词。假模型靠它挑锚点——真模型不需要这个。
常见技术词 = (
    "OAuth", "JWT", "API", "SQL", "Docker", "Redis", "React", "Vue", "Python",
    "Git", "Linux", "Nginx", "HTTP", "JSON", "CSS", "HTML", "Bug", "bug",
    "登录", "爬虫", "接口", "数据库", "部署", "前端", "后端", "报错", "测试",
    "文档", "索引", "缓存", "重构", "压测", "联调", "签名", "依赖",
)

负面词 = ("累", "烦", "崩", "难受", "焦虑", "卡住", "放弃", "不想", "挫败", "慌")
正面词 = ("通了", "跑通", "搞定", "完成", "顺利", "开心", "爽", "松了口气", "解决")


def 假抽取(原文: str, 指定部分: str = "record") -> dict:
    """把一段话「假装」抽成 entries。返回的格式和真模型一样。"""
    原文 = 原文.strip()
    部分 = 指定部分 if 指定部分 != "record" else _猜部分(原文)

    条目 = {
        "did": _压成短句(原文),
        "body": _压成短句(原文, 上限=60),
        "part": 部分,
        "minutes": _猜分钟(原文),
        "outcome": _猜结果(原文),
        "anchors": {
            "tech": _找技术词(原文),
            "people": [],
            "link": _找链接(原文),
        },
        "emotion": {
            "valence": _猜好坏(原文),
            "arousal": _猜强度(原文),
            "trigger": "",
            "quote": _找原话(原文),
        },
        "level": _猜档位(原文),
        "goal": "",
        "blockers": _找卡点(原文),
    }
    return {"entries": [条目]}


def 假看图(原文件名: str, 说明文字: str = "") -> dict:
    """假装看过一张图。

    注意：它**没有真的读图**。所以 ocr_text 写的是实话，
    不会编一段假的 OCR 文本骗你「看起来像真的」。
    """
    return {
        "ocr_text": "（假模型没有真的读这张图。真跑的时候这里会是图里逐行的全部文字。）",
        "digest": f"一张图片：{原文件名}",
        "entries": [
            {
                "did": _压成短句(说明文字 or f"添加图片 {原文件名}"),
                "body": _压成短句(说明文字 or f"添加图片 {原文件名}"),
                "part": "record",
                "minutes": 0,
                "outcome": "done",
                "anchors": {"tech": _找技术词(原文件名 + 说明文字), "people": [], "link": ""},
                "emotion": {"valence": 0.0, "arousal": 0.0, "trigger": "", "quote": ""},
                "level": 2,  # 有图 = 有东西能拿出来
                "goal": "",
                "blockers": [],
            }
        ],
    }


# ── 下面都是「猜」的小函数，每条规则都可以随便改 ──────────────


def _猜部分(原文: str) -> str:
    """这是一条情感记录还是事实记录？"""
    如果是感受类 = any(词 in 原文 for 词 in ("很累", "难受", "焦虑", "崩溃", "不想", "心情"))
    如果没做事 = not any(词 in 原文 for 词 in ("做了", "写完", "跑通", "调通", "学", "看完"))
    if 如果是感受类 and 如果没做事:
        return "emotion"
    return "record"


def _压成短句(原文: str, 上限: int = 60) -> str:
    """把语气词削掉，然后砍到上限以内。

    真实抽取是把修饰删掉、把锚点留住；这里只会「砍尾巴」，因为假模型不懂语义。
    """
    句子 = 原文.replace("\n", " ").strip()
    for 废话 in ("烦死了", "总算", "好不容易", "真的", "其实", "然后", "就是"):
        句子 = 句子.replace(废话, "")
    句子 = re.sub(r"\s+", " ", 句子).strip(" ，,。.")
    return 句子[:上限]


def _猜分钟(原文: str) -> int:
    小时 = re.search(r"(\d+(?:\.\d+)?)\s*(?:个)?小时", 原文)
    if 小时:
        return int(float(小时.group(1)) * 60)
    分钟 = re.search(r"(\d+)\s*分钟", 原文)
    if 分钟:
        return int(分钟.group(1))
    return 0


def _猜结果(原文: str) -> str:
    if any(词 in 原文 for 词 in ("放弃", "不做了", "算了")):
        return "dropped"
    if any(词 in 原文 for 词 in ("卡住", "没通", "失败", "还是不行", "报错")):
        return "stuck"
    return "done"


def _找技术词(原文: str) -> list[str]:
    找到: list[str] = []
    for 词 in 常见技术词:
        if 词.lower() in 原文.lower() and 词 not in 找到:
            找到.append(词)
    # 原文里的英文单词也算锚点（技术名大多是英文）
    for 英文 in re.findall(r"[A-Za-z][A-Za-z0-9_+#.]{1,20}", 原文):
        if 英文 not in 找到:
            找到.append(英文)
    return 找到[:6]


def _找链接(原文: str) -> str:
    链接 = re.search(r"https?://\S+", 原文)
    return 链接.group(0) if 链接 else ""


def _找卡点(原文: str) -> list[str]:
    卡点 = re.search(r"(?:卡在|卡点(?:是|为)?|问题是)\s*([^，。；,;]{2,20})", 原文)
    return [卡点.group(1).strip()] if 卡点 else []


def _猜好坏(原文: str) -> float:
    负 = sum(1 for 词 in 负面词 if 词 in 原文)
    正 = sum(1 for 词 in 正面词 if 词 in 原文)
    if 负 > 正:
        return -0.5
    if 正 > 负:
        return 0.4
    return 0.0


def _猜强度(原文: str) -> float:
    return 0.7 if any(词 in 原文 for 词 in 负面词 + 正面词) else 0.3


def _找原话(原文: str) -> str:
    """挑一句带情绪的话当原话（DESIGN.md §5.4：全文唯一保留原文的地方）。"""
    for 句子 in re.split(r"[。！!；;\n]", 原文):
        句子 = 句子.strip()
        if 句子 and any(词 in 句子 for 词 in 负面词 + 正面词):
            return 句子[:40]
    return ""


def _猜档位(原文: str) -> int:
    """证据档位（DESIGN.md §3.3）。"""
    if any(词 in 原文 for 词 in ("讲给", "教别人", "帮别人看", "写了文档", "写文档")):
        return 3
    if _找链接(原文) or any(词 in 原文 for 词 in ("上线", "部署", "自己写", "从零", "独立做")):
        return 2
    if any(词 in 原文 for 词 in ("照着", "跟着教程", "做了一遍")):
        return 1
    if any(词 in 原文 for 词 in ("学了", "看了", "读了", "了解")):
        return 0
    return 1
