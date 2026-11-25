"""store.py —— 所有「写文件 / 读文件」的事都在这里。

真相源是 markdown（DESIGN.md §3.5）：

- 一条记录  = 一个 .md 文件，放在 vault/now/YYYY-MM/
- 还没抽取的输入 = 一个 .json 文件，放在 vault/inbox/

本文件不联网、不碰数据库。这样即使模型挂了、索引删了，你的记录都还在硬盘上。

字段定义严格照 DESIGN.md §3.4，不多一个也不少一个。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from life import config

# ── 固定的取值范围（DESIGN.md §3.4）────────────────────────────
记录部分 = ("record", "plan", "emotion")  # part：人生记录 / 人生规划 / 情感记录
结果取值 = ("done", "stuck", "dropped")  # outcome：做完 / 卡住 / 放弃
状态取值 = ("pending", "settled", "needs_review")  # status：待处理 / 已定稿 / 待人工看

# 北京时间。项目是给自己用的，先不做多时区。
中国时区 = timezone(timedelta(hours=8))

# vault 里应该有哪些目录（DESIGN.md §3.5）。
# 有些目录第 1 周用不到（chapters/goals/portrait），但先建出来，
# 让你一眼能看到整个结构，不至于以后搬家。
目录清单 = (
    "inbox",
    "inbox/图片暂存",  # 图片在这里等着被读，读完就删（C3：不存原图）
    "now",
    "chapters",
    "goals",
    "portrait",
    "media",  # OCR 全文、缩略图
    "缓存",  # 抽取结果的缓存，删了也不丢数据
)

# 几个占位文件，第一次运行的时候建出来
占位文件 = {
    "core.md": (
        "# 底色\n\n"
        "<!-- 底色最多 50 条，靠证据晋升上来的，第 3 周才有这个功能。 -->\n"
    ),
    "corrections.md": (
        "# 用户纠错\n\n"
        "<!-- 你说的「不对，应该是这样」记在这里，优先级最高。第 3 周实现。 -->\n"
    ),
    "changelog.md": (
        "# 晋升记录\n\n"
        "<!-- 每次「当下 → 章节」「章节 → 底色」都会在这里留一行，第 3 周实现。 -->\n"
    ),
}


class 存储错误(Exception):
    """文件读写出问题时抛这个。"""


# ── 时间 ──────────────────────────────────────────────────────


def 现在() -> datetime:
    """带北京时间、精确到秒的「此刻」。"""
    return datetime.now(中国时区).replace(microsecond=0)


def 时间文本(时间: datetime) -> str:
    """变成 2026-11-25T14:32:00+08:00 这种样子（DESIGN.md §3.4 的 ts 字段）。"""
    return 时间.isoformat()


# ── vault 结构 ────────────────────────────────────────────────


def 确保vault就绪() -> Path:
    """把 vault 的目录和占位文件建出来。已经存在就什么都不做（幂等）。

    每次命令开头都调一次，所以你不用记得「先初始化」。
    """
    vault = config.vault目录()
    for 相对路径 in 目录清单:
        (vault / 相对路径).mkdir(parents=True, exist_ok=True)

    for 文件名, 初始内容 in 占位文件.items():
        路径 = vault / 文件名
        if not 路径.exists():
            _原子写入(路径, 初始内容)

    return vault


def vault结构图() -> list[str]:
    """返回「vault 里现在有什么」，给 life 状态 命令用。"""
    结果 = []
    vault = config.vault目录()
    if not vault.exists():
        return 结果
    for 路径 in sorted(vault.rglob("*")):
        if 路径.is_file() and 路径.name != "index.sqlite":
            结果.append(str(路径.relative_to(vault)).replace("\\", "/"))
    return 结果


# ── 内容指纹（用来防重复）───────────────────────────────────────


def 内容哈希(原文: str, 图片路径: Path | None = None) -> str:
    """给一段输入算一个指纹。

    DESIGN.md §4.1 要求「同一条内容重复提交，不产生两条 entry」。
    做法：先把原文里多余的空格换行抹平，再算 sha256；带图片的把图片字节也算进去。
    这样「今天 很累」和「今天很累」会被认成同一条（中文里那个空格多半是手滑）。
    """
    指纹 = hashlib.sha256()
    指纹.update(_归一化(原文).encode("utf-8"))
    if 图片路径 is not None:
        指纹.update(图片路径.read_bytes())
    return 指纹.hexdigest()


def _归一化(原文: str) -> str:
    """把空白收拾干净：连续空格算一个，中文和中文之间的空格直接删掉。"""
    文本 = " ".join(原文.split())
    return re.sub(r"(?<=[\u4e00-\u9fff]) (?=[\u4e00-\u9fff])", "", 文本)


# ── inbox：先落盘（C5）─────────────────────────────────────────


def 写inbox(输入: dict) -> Path:
    """把一次输入原封不动写进 vault/inbox/<id>.json，并保证已经写到硬盘上。

    DESIGN.md §4.1 第一步。这一步做完，用户就已经「记下来了」，
    后面抽取成功与否都不影响这条数据存在。
    """
    vault = 确保vault就绪()
    路径 = vault / "inbox" / f"{输入['id']}.json"
    _原子写入(路径, json.dumps(输入, ensure_ascii=False, indent=2) + "\n")
    return 路径


def 读inbox(路径: Path) -> dict:
    """读回一个还没抽取的输入。"""
    try:
        return json.loads(路径.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as 错误:
        raise 存储错误(f"这个待抽取文件读不出来：{路径}（{错误}）") from 错误


def 列出inbox() -> list[Path]:
    """列出所有还没抽取成功的输入，按时间从早到晚。"""
    vault = 确保vault就绪()
    目录 = vault / "inbox"
    return sorted(p for p in 目录.glob("*.json") if p.is_file())


def 删inbox(路径: Path) -> None:
    """抽取成功了，把这条从待抽取队列里拿掉。"""
    try:
        路径.unlink(missing_ok=True)
    except OSError as 错误:
        raise 存储错误(f"删不掉这个待抽取文件：{路径}（{错误}）") from 错误


def 图片暂存路径(输入id: str, 原文件: Path) -> Path:
    """图片进 vault 之后叫什么名字。"""
    vault = 确保vault就绪()
    后缀 = 原文件.suffix.lower() or ".png"
    return vault / "inbox" / "图片暂存" / f"{输入id}{后缀}"


def 复制图片到暂存(原文件: Path, 输入id: str) -> Path:
    """把用户给的图片复制进 vault，等着被读。

    为什么要复制：C1 规定所有文件都要在仓库内；而且原图可能马上被用户删掉。
    """
    目标 = 图片暂存路径(输入id, 原文件)
    目标.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(原文件, 目标)
    return 目标


# ── entry：一条记录 ───────────────────────────────────────────


def 新建条目(**字段) -> dict:
    """造一条字段齐全的 entry（DESIGN.md §3.4）。

    没给的字段一律填默认值，这样写 markdown 的时候不会缺行。
    """
    锚点 = 字段.pop("anchors", None) or {}
    情绪 = 字段.pop("emotion", None) or {}

    # ts 可能是字符串，也可能是被 YAML 自动转成的日期对象，统一成字符串。
    # 必须统一：索引里要按 "2026-11" 这种前缀切片查月份，格式一乱就查不到。
    ts值 = 字段.pop("ts")
    if isinstance(ts值, datetime):
        ts值 = 时间文本(ts值)

    条目 = {
        "id": 字段.pop("id"),
        "ts": str(ts值),
        "part": 字段.pop("part", "record"),
        "did": 字段.pop("did", ""),
        "minutes": int(字段.pop("minutes", 0) or 0),
        "outcome": 字段.pop("outcome", "done"),
        "anchors": {
            "tech": list(锚点.get("tech") or []),
            "people": list(锚点.get("people") or []),
            "link": str(锚点.get("link") or ""),
        },
        "emotion": {
            "valence": float(情绪.get("valence") or 0.0),
            "arousal": float(情绪.get("arousal") or 0.0),
            "trigger": str(情绪.get("trigger") or ""),
            "quote": str(情绪.get("quote") or ""),
        },
        "level": int(字段.pop("level", 0) or 0),
        "goal": str(字段.pop("goal", "") or ""),
        "chapter": str(字段.pop("chapter", "") or ""),
        "blockers": list(字段.pop("blockers", None) or []),
        "private": bool(字段.pop("private", False)),
        "status": 字段.pop("status", "settled"),
        # body 不进 front-matter，它是 markdown 的正文
        "body": str(字段.pop("body", "") or ""),
    }

    if 条目["body"] == "":
        条目["body"] = 条目["did"]

    if 字段:
        # 剩下的都是没定义的字段，说明代码里打错字了，直接报出来
        raise 存储错误(f"有条目字段不在设计里：{sorted(字段)}")

    return 条目


def 分配id(时间: datetime) -> tuple[str, datetime]:
    """给一条新记录分配 id。id 就是文件名（20261125-143200）。

    同一秒里产生多条（一段话被拆成几条）会撞名，所以冲突就往后挪 1 秒。
    同时也避开 inbox 里还压着的同名文件——不然同一秒敲两次 add，
    第二次会把第一次待抽取的 json 覆盖掉。
    """
    当前 = 时间
    vault = config.vault目录()
    for _ in range(120):
        id = 当前.strftime("%Y%m%d-%H%M%S")
        月目录 = vault / "now" / 当前.strftime("%Y-%m")
        被占用 = (月目录 / f"{id}.md").exists() or (vault / "inbox" / f"{id}.json").exists()
        if not 被占用:
            return id, 当前
        当前 = 当前 + timedelta(seconds=1)
    raise 存储错误("同一分钟里产生的记录太多了，id 分配不出来。")


def 条目路径(id: str, ts: str) -> Path:
    """这条记录该存在哪：vault/now/YYYY-MM/<id>.md"""
    月目录 = ts[:7]  # 2026-11
    return config.vault目录() / "now" / 月目录 / f"{id}.md"


def 写条目(条目: dict) -> Path:
    """把一条 entry 写成 markdown。"""
    路径 = 条目路径(条目["id"], 条目["ts"])
    路径.parent.mkdir(parents=True, exist_ok=True)
    _原子写入(路径, 格式化成markdown(条目))
    return 路径


def 读条目(路径: Path) -> dict:
    """读回一条 entry。"""
    try:
        文本 = 路径.read_text(encoding="utf-8")
    except OSError as 错误:
        raise 存储错误(f"这个记录文件读不出来：{路径}（{错误}）") from 错误
    return 从markdown解析(文本, 来源=路径)


def 遍历条目() -> list[Path]:
    """列出所有记录文件。索引就是从这些文件重建出来的。"""
    vault = config.vault目录()
    目录 = vault / "now"
    if not 目录.exists():
        return []
    return sorted(目录.rglob("*.md"))


# ── markdown 的格式与解析 ─────────────────────────────────────


def 格式化成markdown(条目: dict) -> str:
    """按 DESIGN.md §3.4 的样子拼一个 markdown 文件。

    为什么手写而不是用 yaml.dump：yaml.dump 会自己换行、自己加引号，
    排出来的顺序和你设计文档里看到的不一样，出问题很难对照。
    """
    锚点 = 条目["anchors"]
    情绪 = 条目["emotion"]

    行 = [
        "---",
        f"id: {条目['id']}",
        f"ts: {条目['ts']}",
        f"part: {条目['part']}",
        f"did: {_文本(条目['did'])}",
        f"minutes: {条目['minutes']}",
        f"outcome: {条目['outcome']}",
        "anchors:",
        f"  tech: {_列表(锚点['tech'])}",
        f"  people: {_列表(锚点['people'])}",
        f"  link: {_文本(锚点['link'])}",
        "emotion:",
        f"  valence: {条目['emotion']['valence']}",
        f"  arousal: {条目['emotion']['arousal']}",
        f"  trigger: {_文本(情绪['trigger'])}",
        f"  quote: {_文本(情绪['quote'])}",
        f"level: {条目['level']}",
        f"goal: {_文本(条目['goal'])}",
        f"chapter: {_文本(条目['chapter'])}",
        f"blockers: {_列表(条目['blockers'])}",
        f"private: {'true' if 条目['private'] else 'false'}",
        f"status: {条目['status']}",
        "---",
        条目["body"],
        "",
    ]
    return "\n".join(行)


def 从markdown解析(文本: str, 来源: Path | None = None) -> dict:
    """把 markdown 拆成「front-matter（开头那段键值）+ 正文」。"""
    文本 = 文本.replace("\r\n", "\n")
    if not 文本.startswith("---\n"):
        raise 存储错误(f"这个文件开头缺了 ---，不是一条记录：{来源}")

    结束位置 = 文本.find("\n---\n", 4)
    if 结束位置 == -1:
        # 理论上不会发生，除非文件被手动改坏了
        raise 存储错误(f"这个文件的开头那段没有结尾的 ---：{来源}")

    头文本 = 文本[4:结束位置]
    正文 = 文本[结束位置 + 5 :].strip("\n")

    try:
        头 = yaml.safe_load(头文本) or {}
    except yaml.YAMLError as 错误:
        raise 存储错误(f"这个文件开头那段格式坏了：{来源}（{错误}）") from 错误

    if not isinstance(头, dict):
        raise 存储错误(f"这个文件开头那段不是一个键值表：{来源}")

    for 必须有的 in ("id", "ts", "part"):
        if 必须有的 not in 头:
            raise 存储错误(f"这个文件缺了 {必须有的} 字段：{来源}")

    条目 = 新建条目(**{**头, "body": 正文})
    # 文件名必须和 id 一致，不然索引和文件会对不上
    if 来源 is not None and 来源.stem != 条目["id"]:
        raise 存储错误(
            f"文件名（{来源.stem}）和里面的 id（{条目['id']}）不一致：{来源}"
        )
    return 条目


# ── 小工具 ───────────────────────────────────────────────────


def _文本(值: str) -> str:
    """一个字符串在 YAML 里怎么写才不会被误解（统一用双引号包起来）。"""
    return json.dumps(str(值), ensure_ascii=False)


def _列表(值: list) -> str:
    """一个列表在 YAML 里怎么写：["OAuth", "state 参数"]"""
    return "[" + ", ".join(_文本(x) for x in 值) + "]"


def _原子写入(路径: Path, 内容: str) -> None:
    """先写临时文件再改名。

    这样万一写到一半断电，原来的文件还是完整的——不会留下半个 JSON。
    """
    临时 = 路径.with_name(路径.name + ".tmp")
    临时.write_text(内容, encoding="utf-8")
    临时.replace(路径)
