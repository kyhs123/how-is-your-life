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

# 正文上限（DESIGN.md §5.2 第 4 条）。extract.py 也引用这一个常量，别再各写一份。
正文上限 = 60

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
        "<!-- 底色最多 50 条，只能靠证据晋升上来；章节→底色还没实现，现在可以手写。 -->\n"
    ),
    "corrections.md": (
        "# 用户纠错\n\n"
        "<!-- 你说的「不对，应该是这样」记在这里，优先级最高。（还没做） -->\n"
    ),
    "changelog.md": (
        "# 晋升记录\n\n"
        "<!-- 每次提名、晋升、拒绝都会在这里留一行（life settle / life promote 自动写）。 -->\n"
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
        # 人话时间：可以写 "2023"、"2023-09"、"大一"，也可以是空（时间不详）。
        # ts 仍然是给程序用的时间戳；when 是给人看的。两个都要，因为「不记得哪天」很常见。
        "when": str(字段.pop("when", "") or ""),
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


def 找条目文件(记录id: str) -> Path | None:
    """按 id 找那条记录的文件（id 就是文件名）。"""
    检查记录id(记录id)
    目录 = config.vault目录() / "now"
    if not 目录.exists():
        return None
    for 路径 in 目录.rglob(f"{记录id}.md"):
        return 路径
    return None


# 记录 id 只允许这些字符。网页会把 id 拼进路径和 URL，
# 所以必须挡住 `/`、`..` 之类的东西（否则就能越出 vault/ 读别的文件）。
记录id允许 = re.compile(r"^[0-9A-Za-z_\-\u4e00-\u9fff]{1,80}$")


def 检查记录id(记录id: str) -> None:
    if not 记录id or not 记录id允许.match(记录id):
        raise 存储错误(f"记录 id 不合法：{记录id!r}")


def 改条目状态(记录id: str, 新状态: str) -> dict:
    """改一条记录的状态（网页界面那个「确认」按钮用的）。"""
    return 改条目字段(记录id, status=新状态)


def 改条目字段(
    记录id: str,
    *,
    did: str | None = None,
    level: int | None = None,
    outcome: str | None = None,
    status: str | None = None,
    when: str | None = None,
) -> dict:
    """改一条记录的四个字段（网页「单条」页面用的）。

    只允许改这四个。`private` 不能在这里改——那会改变对用户的隐私承诺，
    误操作的代价太大（详见 docs/WEBUI.md §2.3）。
    """
    路径 = 找条目文件(记录id)
    if 路径 is None:
        raise 存储错误(f"找不到记录 {记录id}。")

    条目 = 读条目(路径)

    if did is not None:
        句子 = " ".join(did.split())
        if not 句子:
            raise 存储错误("那句话不能空着。")
        if len(句子) > 正文上限:
            raise 存储错误(f"那句话有 {len(句子)} 个字，超过 {正文上限} 字上限。")
        条目["did"] = 句子
        if not 条目["body"]:
            条目["body"] = 句子

    if level is not None:
        if level not in (0, 1, 2, 3):
            raise 存储错误(f"档位只能是 0/1/2/3，你给的是 {level}。")
        条目["level"] = level

    if outcome is not None:
        if outcome not in 结果取值:
            raise 存储错误(f"结果只能是 {list(结果取值)}。")
        条目["outcome"] = outcome

    if status is not None:
        if status not in 状态取值:
            raise 存储错误(f"状态只能是 {list(状态取值)}。")
        条目["status"] = status

    if when is not None:
        # 只改人话时间；时间戳（ts）不动 —— 改 ts 会让文件和目录对不上
        条目["when"] = when.strip()[:40]

    写条目(条目)
    return 条目


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
        f"when: {_文本(条目['when'])}",
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
    """把 markdown 拆成「front-matter（开头那段键值）+ 正文」，再变成一条 entry。"""
    头, 正文 = 解析front_matter(文本, 来源)

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


def 解析front_matter(文本: str, 来源: Path | None = None) -> tuple[dict, str]:
    """通用的「拆开头那段」：entry / 目标 / 章节都用同一种文件格式。"""
    文本 = 文本.replace("\r\n", "\n")
    if not 文本.startswith("---\n"):
        raise 存储错误(f"这个文件开头缺了 ---：{来源}")

    结束位置 = 文本.find("\n---\n", 4)
    if 结束位置 == -1:
        raise 存储错误(f"这个文件的开头那段没有结尾的 ---：{来源}")

    头文本 = 文本[4:结束位置]
    正文 = 文本[结束位置 + 5 :].strip("\n")

    try:
        头 = yaml.safe_load(头文本) or {}
    except yaml.YAMLError as 错误:
        raise 存储错误(f"这个文件开头那段格式坏了：{来源}（{错误}）") from 错误

    if not isinstance(头, dict):
        raise 存储错误(f"这个文件开头那段不是一个键值表：{来源}")

    return 头, 正文


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


def _写front_matter(键值: dict) -> str:
    """把字典渲染成开头那段。entry / 目标 / 章节共用。

    简单的值（枚举、日期、数字）不加引号，长得像人话的才加——这样文件读起来和
    DESIGN.md 里的示例一致：``status: active`` / ``title: "OAuth 调试"``。
    """
    行 = ["---"]
    for 键, 值 in 键值.items():
        if isinstance(值, bool):
            行.append(f"{键}: {'true' if 值 else 'false'}")
        elif isinstance(值, (int, float)):
            行.append(f"{键}: {值}")
        elif isinstance(值, (list, tuple)):
            行.append(f"{键}: {_列表(list(值))}")
        else:
            文本 = str(值)
            if 文本 and re.fullmatch(r"[A-Za-z0-9_\-\.\+:]+", 文本):
                行.append(f"{键}: {文本}")
            else:
                行.append(f"{键}: {_文本(文本)}")
    行.append("---")
    return "\n".join(行)


# ── 目标（DESIGN.md §3.4 goal）─────────────────────────────────

期限取值 = ("short", "term", "long")  # 2周~1月 / 1学期~半年 / 1~3年
目标状态取值 = ("active", "done", "stopped", "paused")


def 清洗文件名(名字: str) -> str:
    """把标题变成能当文件名/命令参数用的东西。

    中文一律保留（你自己的东西，看得懂最重要），只把 Windows 不允许的字符换掉。
    """
    结果 = re.sub(r'[\\/:*?"<>|\n\r\t]', "-", 名字).strip().strip(".")
    结果 = re.sub(r"-{2,}", "-", 结果)
    if not 结果:
        raise 存储错误("标题是空的，或者全是不能当文件名的字符。")
    return 结果[:60]


def 新建目标(**字段) -> dict:
    标题 = str(字段.pop("title", "") or "").strip()
    if not 标题:
        raise 存储错误("目标得有个标题。")

    期限 = 字段.pop("horizon", "term")
    if 期限 not in 期限取值:
        raise 存储错误(f"horizon 只能是 {list(期限取值)} 之一，你给的是 {期限!r}。")

    状态 = 字段.pop("status", "active")
    if 状态 not in 目标状态取值:
        raise 存储错误(f"目标状态只能是 {list(目标状态取值)} 之一，你给的是 {状态!r}。")

    return {
        "id": str(字段.pop("id", "") or 清洗文件名(标题)),
        "title": 标题,
        "horizon": 期限,
        "why": str(字段.pop("why", "") or ""),
        "started": str(字段.pop("started", "") or 现在().date().isoformat()),
        "due": str(字段.pop("due", "") or ""),
        "status": 状态,
        # derived = 进度从记录推（默认）；manual = 你自己说
        "progress_mode": str(字段.pop("progress_mode", "derived")),
        "parent": str(字段.pop("parent", "") or ""),
        "body": str(字段.pop("body", "") or ""),
    }


def 写目标(目标: dict) -> Path:
    路径 = 确保vault就绪() / "goals" / f"{清洗文件名(目标['id'])}.md"
    表 = {键: 值 for 键, 值 in 目标.items() if 键 != "body"}
    _原子写入(路径, _写front_matter(表) + "\n" + (目标.get("body") or "") + "\n")
    return 路径


def 读目标(路径: Path) -> dict:
    头, 正文 = 解析front_matter(路径.read_text(encoding="utf-8"), 来源=路径)
    return 新建目标(**{**头, "body": 正文})


def 遍历目标() -> list[Path]:
    目录 = 确保vault就绪() / "goals"
    return sorted(目录.glob("*.md"))


def 全部目标() -> list[dict]:
    结果 = []
    for 路径 in 遍历目标():
        try:
            结果.append(读目标(路径))
        except 存储错误:
            continue  # 手改坏了的文件跳过，不影响别的
    return 结果


# ── 章节（DESIGN.md §3.4 chapter）─────────────────────────────

章节状态取值 = ("active", "dormant", "promoted")


def 新建章节(**字段) -> dict:
    标题 = str(字段.pop("title", "") or "").strip()
    if not 标题:
        raise 存储错误("章节得有个标题。")

    状态 = 字段.pop("status", "active")
    if 状态 not in 章节状态取值:
        raise 存储错误(f"章节状态只能是 {list(章节状态取值)} 之一，你给的是 {状态!r}。")

    return {
        "id": str(字段.pop("id", "") or 清洗文件名(标题)),
        "title": 标题,
        "started": str(字段.pop("started", "") or 现在().date().isoformat()),
        "layers": list(字段.pop("layers", None) or ["now"]),
        "entry_count": int(字段.pop("entry_count", 0) or 0),
        "level_max": int(字段.pop("level_max", 0) or 0),
        "status": 状态,
        "last_evidence": str(字段.pop("last_evidence", "") or 现在().date().isoformat()),
        "body": str(字段.pop("body", "") or ""),
    }


def 写章节(章节: dict) -> Path:
    路径 = 确保vault就绪() / "chapters" / f"{清洗文件名(章节['id'])}.md"
    表 = {键: 值 for 键, 值 in 章节.items() if 键 != "body"}
    _原子写入(路径, _写front_matter(表) + "\n" + (章节.get("body") or "") + "\n")
    return 路径


def 读章节(路径: Path) -> dict:
    头, 正文 = 解析front_matter(路径.read_text(encoding="utf-8"), 来源=路径)
    return 新建章节(**{**头, "body": 正文})


def 遍历章节() -> list[Path]:
    目录 = 确保vault就绪() / "chapters"
    return sorted(目录.glob("*.md"))


def 全部章节() -> list[dict]:
    结果 = []
    for 路径 in 遍历章节():
        try:
            结果.append(读章节(路径))
        except 存储错误:
            continue
    return 结果


# ── 晋升日志（DESIGN.md §3.2）─────────────────────────────────


def 追加日志(一句话: str, *, 带日期: bool = True) -> Path:
    """往 vault/changelog.md 追加一行。

    DESIGN.md §3.2：每次晋升必须生成一条可见记录。
    格式是「日期 + 一句话」，换行时下面的说明行可以不带日期。
    """
    路径 = 确保vault就绪() / "changelog.md"
    前缀 = f"{现在().date().isoformat()} " if 带日期 else ""
    with 路径.open("a", encoding="utf-8") as 文件:
        文件.write(f"{前缀}{一句话}\n")
    return 路径


def 读日志() -> list[str]:
    """读 changelog.md 里的正文行（去掉标题和注释）。"""
    路径 = 确保vault就绪() / "changelog.md"
    文本 = 路径.read_text(encoding="utf-8") if 路径.exists() else ""
    文本 = re.sub(r"<!--.*?-->", "", 文本, flags=re.S)
    行们 = [行.strip() for 行 in 文本.splitlines() if 行.strip()]
    return [行 for 行 in 行们 if not 行.startswith("#")]


# ── 底色（DESIGN.md §3.4 core：一个文件装全部，≤50 条）────────


def 读底色项() -> list[dict]:
    """把 core.md 拆成一条条：``## 名字`` 加它下面的几行。"""
    路径 = 确保vault就绪() / "core.md"
    文本 = 路径.read_text(encoding="utf-8") if 路径.exists() else ""
    文本 = re.sub(r"<!--.*?-->", "", 文本, flags=re.S)

    项们: list[dict] = []
    当前: dict | None = None
    for 行 in 文本.splitlines():
        if 行.startswith("## "):
            当前 = {"name": 行[3:].strip(), "lines": []}
            项们.append(当前)
        elif 当前 is not None and 行.strip():
            当前["lines"].append(行.strip())
    return 项们


def 追加底色项(名字: str, 行们: list[str]) -> Path:
    路径 = 确保vault就绪() / "core.md"
    with 路径.open("a", encoding="utf-8") as 文件:
        文件.write(f"\n## {名字}\n")
        for 行 in 行们:
            文件.write(f"- {行}\n")
    return 路径


# ── media 与记录的关联 ───────────────────────────────────────
#
# 为什么需要这张表：media 里的文件名用的是「输入 id」，而记录用的是「记录 id」，
# 两者不是一回事（一条输入可能拆成多条记录）。光靠文件名对不上，
# 所以这里记一份对应关系；没有对应记录的文件才可能是孤儿。


def media关联路径() -> Path:
    return 确保vault就绪() / "media" / "关联.json"


def 读media关联() -> dict:
    """{文件名: [记录 id, ...]}"""
    路径 = media关联路径()
    if not 路径.exists():
        return {}
    try:
        数据 = json.loads(路径.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return 数据 if isinstance(数据, dict) else {}


def 写media关联(文件名: str, 记录id们: list[str]) -> None:
    关联 = 读media关联()
    旧 = list(关联.get(文件名) or [])
    关联[文件名] = sorted({*旧, *记录id们})
    _原子写入(
        media关联路径(),
        json.dumps(关联, ensure_ascii=False, indent=2) + "\n",
    )
