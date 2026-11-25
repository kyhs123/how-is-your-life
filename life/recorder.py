"""recorder.py —— 记一条记录的完整链路。

命令行（`life add`）和本机网页（`life server` 的「记一条」）走的是**同一段代码**，
不是两份实现。这一点很重要：落盘顺序、去重、图片处理只要有两份，早晚会不一致。

顺序（DESIGN.md §4.1 / C5）：

    算指纹 → 查重复 → 写 vault/inbox/<id>.json（★这一行之后内容就不会丢了）
    → 调模型抽取 → 写 vault/now/<月>/<id>.md → 建索引 → 删 inbox → 写缓存

抽取失败不影响「已经记下来」这件事，inbox 会留着等 `life retry`。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from life import config, extract, index, llm, store
from life import uploads as uploads模块

提示函数 = Callable[[str], None]


def _不说(_: str) -> None:
    pass


def 记录一条(
    原文: str = "",
    *,
    图片: Path | None = None,
    文档: Path | None = None,
    文档原名: str = "",
    保留原文件: bool = False,
    情感: bool = False,
    私密: bool = False,
    保留图片: bool = False,
    用假模型: bool = False,
    时间: str = "",
    提示: 提示函数 | None = None,
) -> dict:
    """记一条。返回结果字典，调用方负责把结果变成屏幕上的一句话。

    图片和文档走同一条链路，区别只在「怎么变成文字」：
        图片 → 视觉模型一次调用（OCR 全文 + 摘要 + claims）
        文档 → 本地抽文本（txt / md / docx），再走文本抽取

    返回值：
        {
          "状态": "重复" | "成功" | "抽取失败" | "配置错误" | "输入有问题",
          "路径们": [Path],          # 写出来的记录文件
          "收件": Path | None,        # inbox 里那个 json
          "错误": str,
        }
    """
    说 = 提示 or _不说

    if not 原文.strip() and 图片 is None and 文档 is None:
        return {"状态": "输入有问题", "路径们": [], "收件": None, "错误": "什么都没有输入。"}

    if 图片 is not None and not 图片.exists():
        return {"状态": "输入有问题", "路径们": [], "收件": None, "错误": f"找不到这张图：{图片}"}

    if 文档 is not None and not 文档.exists():
        return {"状态": "输入有问题", "路径们": [], "收件": None, "错误": f"找不到这个文件：{文档}"}

    vault = store.确保vault就绪()
    # 「什么时候」可以写得含糊（大一 / 2023 / 2023-09），也可能是空的。
    # 能转成日期就用它做时间戳；转不出来（比如「大一」）就把时间戳记成录入时刻，
    # 人话时间原样存进 when —— 见 docs/WEBUI.md §2.5。
    try:
        某天, 时间说明 = 解析过去时间(时间)
    except ValueError as 错误:
        # 比如「不能补记未来的事」——这是输入问题，不是崩了
        return {"状态": "输入有问题", "路径们": [], "收件": None, "错误": str(错误)}
    此刻 = _某天中午(某天) if 某天 is not None else store.现在()
    输入id, _ = store.分配id(此刻)

    # ① 文件先复制进 vault（C1：必须在仓库内；也保证原始文件被删掉也不影响）
    暂存: Path | None = None
    if 图片 is not None or 文档 is not None:
        来源文件 = 图片 if 图片 is not None else 文档
        try:
            暂存 = store.复制图片到暂存(来源文件, 输入id)
        except OSError as 错误:
            return {
                "状态": "输入有问题",
                "路径们": [],
                "收件": None,
                "错误": f"复制文件失败：{错误}",
            }

    # ② 文档：立刻把全文抽出来存好（原文件之后可能被删，这段全文是它唯一的话）
    全文 = ""
    if 文档 is not None and 暂存 is not None:
        try:
            全文 = uploads模块.抽文本(暂存)
        except uploads模块.上传错误 as 错误:
            暂存.unlink(missing_ok=True)
            return {"状态": "输入有问题", "路径们": [], "收件": None, "错误": str(错误)}

        if not 全文.strip():
            暂存.unlink(missing_ok=True)
            return {
                "状态": "输入有问题",
                "路径们": [],
                "收件": None,
                "错误": "这个文件里没读到文字（可能是扫描件或空文档）。",
            }

        _存全文(vault, 输入id, 文档原名 or 暂存.name, 全文)
        说(f"· 已从文件里抽出 {len(全文)} 个字，存在 vault/media/{输入id}.md")

        if not 原文.strip():
            原文 = uploads模块.送模型的片段(全文)

    # ③ 算指纹，看是不是重复提交（§4.1 幂等）
    指纹 = store.内容哈希(原文, 暂存)
    已有 = extract.读缓存(指纹)
    if 已有 and any((vault / 相对).exists() for 相对 in 已有.get("entry_paths", [])):
        if 暂存 is not None:
            暂存.unlink(missing_ok=True)
        说("· 这条之前已经记过了，不重复存：")
        for 相对 in 已有.get("entry_paths", []):
            说(f"    vault/{相对}")
        return {"状态": "重复", "路径们": [], "收件": None, "错误": ""}

    # ④ 先落盘（C5）。这一行执行完，这条内容就不会丢了。
    if 图片 is not None:
        种类 = "image"
    elif 文档 is not None:
        种类 = "document"
    else:
        种类 = "text"

    输入 = {
        "格式": 1,
        "id": 输入id,
        "ts": store.时间文本(此刻),
        "kind": 种类,
        "when": 时间.strip(),
        "原文": 原文,
        "部分": "emotion" if 情感 else "record",
        "private": 私密,
        "keep_image": 保留图片 or 保留原文件,
        "图片": str(暂存.relative_to(vault)).replace("\\", "/") if 暂存 else "",
        "图片原名": 图片.name if 图片 is not None else 文档原名,
        "内容指纹": 指纹,
        "时间提示": "".join(
            片段
            for 片段 in (
                (
                    f"这条记录是补记的，发生在「{时间.strip()}」"
                    f"（时间戳记为 {此刻.date().isoformat()}）。"
                    "正文里不要写「今天」「昨天」「刚刚」，直接写事实。"
                )
                if 时间.strip()
                else "",
                (
                    "这段内容取自一份文件（简历 / 笔记之类），里面往往有好几件事。"
                    "请尽量拆成多条，每条只讲一件事，每条都要带自己的锚点"
                    "（技术名、项目名、数字、时间）。宁可多拆，不要压成一条。"
                )
                if 文档 is not None
                else "",
            )
            if 片段
        ),
        "尝试次数": 0,
        "最后错误": "",
    }
    收件路径 = store.写inbox(输入)
    说(f"· 已存好：vault/inbox/{收件路径.name}")

    # ⑤ 抽取（失败也不影响上面那条已经存好的记录）
    try:
        路径们, 结果 = 抽取并保存(输入, 用假模型=用假模型, 提示=说)
    except llm.网络错误 as 错误:
        return {"状态": "抽取失败", "路径们": [], "收件": 收件路径, "错误": str(错误)}
    except config.配置错误 as 错误:
        return {"状态": "配置错误", "路径们": [], "收件": 收件路径, "错误": str(错误)}
    except (llm.模型错误, extract.抽取错误, index.索引错误) as 错误:
        return {"状态": "抽取失败", "路径们": [], "收件": 收件路径, "错误": str(错误)}

    # ⑥ 收尾：清掉待抽取文件、处理文件、写缓存
    store.删inbox(收件路径)
    处理文件(输入, vault, 暂存, 结果, 提示=说)
    extract.写缓存(指纹, 结果, 路径们)

    for 路径 in 路径们:
        说(f"√ 记下了：vault/{str(路径.relative_to(vault)).replace(chr(92), '/')}")

    return {"状态": "成功", "路径们": 路径们, "收件": 收件路径, "错误": ""}


def _存全文(vault: Path, 输入id: str, 原名: str, 全文: str) -> None:
    """文档抽出来的全文，存成 markdown。原文件删掉之后，这是它唯一的「原话」。"""
    正文 = (
        f"# 文件全文\n\n"
        f"来源：{原名}\n\n"
        f"---\n\n"
        f"{全文}\n"
    )
    (vault / "media" / f"{输入id}.md").write_text(正文, encoding="utf-8")


def 抽取并保存(
    输入: dict, *, 用假模型: bool, 图片: Path | None = None, 提示: 提示函数 | None = None
) -> tuple[list[Path], dict]:
    """一次输入 → 抽取 → 写成 markdown → 进索引。返回（文件路径列表，抽取结果）。"""
    说 = 提示 or _不说
    vault = config.vault目录()

    # 只有「图片」才走视觉通道。文档在上游已经把文字抽好了，
    # 再把 .docx 的字节当成 base64 图片发过去，上游会直接 400（实测踩过）。
    if 图片 is None and 输入.get("kind") == "image" and 输入.get("图片"):
        可能 = vault / 输入["图片"]
        图片 = 可能 if 可能.exists() else None

    结果 = extract.抽取(
        输入.get("原文", ""),
        部分=输入.get("部分", "record"),
        图片路径=图片,
        原文文件名=输入.get("图片原名", ""),
        私密=bool(输入.get("private")),
        用假模型=用假模型,
        内容指纹=输入.get("内容指纹", ""),
        时间提示=输入.get("时间提示", ""),
    )

    if 结果["status"] == "needs_review" and 结果.get("备注"):
        说(f"· {结果['备注']}")

    连接 = index.连接索引()
    try:
        from datetime import datetime

        时间 = datetime.fromisoformat(输入["ts"])
        路径们: list[Path] = []
        for 一条 in 结果["entries"]:
            记录id, 时间 = store.分配id(时间)
            条目 = store.新建条目(
                id=记录id,
                ts=store.时间文本(时间),
                when=输入.get("when", ""),
                private=bool(输入.get("private")),
                status=结果["status"],
                **一条,
            )
            路径 = store.写条目(条目)
            index.写入条目(连接, 条目)
            路径们.append(路径)
        # 让后面写 media 的时候知道这些全文/原件属于哪些记录
        输入["记录id们"] = [p.stem for p in 路径们]
        return 路径们, 结果
    finally:
        连接.close()


def 处理文件(
    输入: dict,
    vault: Path,
    暂存: Path | None,
    结果: dict,
    *,
    提示: 提示函数 | None = None,
) -> None:
    """按设计处理上传的文件：全文留下，原文件删掉（除非用户勾了「保留原文件」）。

    图片的全文 = OCR 结果；文档的全文在抽取前就已经写好了（见 _存全文）。
    """
    说 = 提示 or _不说
    if 暂存 is None:
        return

    if 输入.get("kind") == "image":
        正文 = (
            "# 图片原文（OCR）\n\n"
            f"{结果.get('ocr_text') or '（没有识别出文字）'}\n\n"
            f"# 摘要\n\n{结果.get('digest') or '（没有摘要）'}\n"
        )
        文件名 = f"{输入['id']}.md"
        (vault / "media" / 文件名).write_text(正文, encoding="utf-8")
        store.写media关联(文件名, 输入.get("记录id们") or [])

    if 输入.get("keep_image") or 输入.get("keep_file"):
        # 保留时的文件名用记录 id，不用上传时的原名（原名不可信，也容易重名）
        目标 = vault / "media" / f"{输入['id']}{暂存.suffix}"
        目标.parent.mkdir(parents=True, exist_ok=True)
        暂存.replace(目标)
        store.写media关联(目标.name, 输入.get("记录id们") or [])
        说(f"· 原文件按你的要求留下了：vault/media/{目标.name}")
    else:
        暂存.unlink(missing_ok=True)


# ── 补记历史时用的小工具 ─────────────────────────────────────


def _某天中午(某天: date) -> datetime:
    """把「哪一天」变成带时间戳的时刻。

    用中午 12 点，避开时区边界和「零点算前一天」这类坑。
    """
    return datetime(某天.year, 某天.month, 某天.day, 12, 0, 0, tzinfo=store.中国时区)


def 解析过去时间(文本: str) -> tuple[date | None, str]:
    """把「什么时候」变成（日期 or None，给人看的说明）。

    能认出来就转日期：`2023` / `2023-09` / `2023-09-15` / `2023年9月`。
    认不出来（`大一`、`记不清了`）就返回 None —— 那就是**时间不详**，
    不要把「记不清」硬塞成某一天。

    缺的部分按月/年初补，并且明确告诉你补了什么（页面会显示这句说明）。
    """
    原 = (文本 or "").strip()
    if not 原:
        return None, "现在"

    规范 = (
        原.replace("/", "-")
        .replace(".", "-")
        .replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .strip("-")
    )
    匹配 = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", 规范)
    if not 匹配:
        return None, f"时间不详（「{原}」认不出是哪天，按录入时间存，when 里留着原话）"

    年 = int(匹配.group(1))
    月 = int(匹配.group(2) or 1)
    日 = int(匹配.group(3) or 1)

    try:
        某天 = date(年, 月, 日)
    except ValueError:
        return None, f"时间不详（「{原}」不是真实存在的日期）"

    if 某天 > store.现在().date():
        raise ValueError("不能补记未来的事。")

    if not 匹配.group(2):
        return 某天, f"{年} 年（只知道年份，时间戳记为 {某天.isoformat()}）"
    if not 匹配.group(3):
        return 某天, f"{年} 年 {月} 月（只知道月份，时间戳记为 {某天.isoformat()}）"
    return 某天, 某天.isoformat()


def 解析过去日期(文本: str) -> tuple[date, str]:
    """要一个确定日期时用这个（认不出就报错）。"""
    某天, 说明 = 解析过去时间(文本)
    if 某天 is None:
        raise ValueError(说明)
    return 某天, 说明


def 补抽(提示: 提示函数 | None = None) -> dict:
    """把 inbox 里没抽成的再跑一遍（`life retry` 和网页上的「补抽」按钮共用）。"""
    说 = 提示 or _不说
    vault = store.确保vault就绪()
    文件们 = store.列出inbox()
    成功 = 0
    失败 = 0
    错误们: list[str] = []

    for 路径 in 文件们:
        try:
            输入 = store.读inbox(路径)
        except store.存储错误 as 错误:
            说(f"× {错误}")
            失败 += 1
            continue

        暂存 = vault / 输入["图片"] if 输入.get("图片") else None
        if 暂存 is not None and not 暂存.exists():
            暂存 = None
        图片参数 = 暂存 if 输入.get("kind") == "image" else None

        try:
            路径们, 结果 = 抽取并保存(输入, 用假模型=False, 图片=图片参数, 提示=说)
        except (llm.模型错误, extract.抽取错误, index.索引错误, config.配置错误) as 错误:
            说(f"× {路径.name} 还是不行：{错误}")
            错误们.append(str(错误))
            失败 += 1
            continue

        store.删inbox(路径)
        try:
            处理文件(输入, vault, 暂存, 结果, 提示=说)
        except Exception as 错误:  # noqa: BLE001 —— 收尾失败不算整体失败
            说(f"· 收尾时出了点问题（记录本身已经存好）：{错误}")
        extract.写缓存(输入.get("内容指纹", ""), 结果, 路径们)
        for 一条 in 路径们:
            说(f"√ 记下了：vault/{str(一条.relative_to(vault)).replace(chr(92), '/')}")
        成功 += 1

    return {"成功": 成功, "失败": 失败, "错误": 错误们[:3], "总数": len(文件们)}
