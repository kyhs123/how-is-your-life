"""goalchat.py —— 目标上的「老师」：看着这个目标的证据，帮你规划下一步。

和 `life ask` 的分工：
    ask        回答「我是什么样的人 / 我以前也这样过吗」——翻全部记录
    goalchat   回答「这个目标接下来怎么办」——**只看这个目标名下的证据**

为什么要分开：目标页上问「我该从哪开始」，如果模型拿到的是全部记录，
它会满嘴跑火车地泛泛而谈；只给它这个目标的证据（几条、什么档、卡在哪），
它才可能说出「你现在只有接触档，先去把一件小事做成能讲的样子」这种话。

人设写在 prompts/goal_chat.md 里：专业、有规划、像老师。
"""

from __future__ import annotations

import json
from pathlib import Path

from life import config, goal, llm, store

提问模板 = (
    "我该从哪开始？",
    "接下来一周做什么？",
    "我卡住了，帮我拆一下",
)

最近几轮 = 3          # 上下文里带几轮旧对话（多了会把证据挤掉）


def 对话路径(目标: dict) -> Path:
    """一个目标一个文件：vault/dialogue/<目标 id>.jsonl

    为什么是 jsonl 而不是 markdown：对话里什么字符都可能有（问答里都可能有 ## 和空行），
    一行一个 JSON 解析最稳；而且一行坏了只丢一行，不会整份读不出来。
    """
    目录 = store.确保vault就绪() / "dialogue"
    目录.mkdir(parents=True, exist_ok=True)
    return 目录 / f"{store.清洗文件名(目标['id'])}.jsonl"


def 读对话(目标: dict, *, 最多: int | None = None) -> list[dict]:
    """按时间正序读回来。坏行直接跳过——聊天记录不值得为了它报错。"""
    路径 = 对话路径(目标)
    if not 路径.exists():
        return []
    轮们: list[dict] = []
    for 行 in 路径.read_text(encoding="utf-8").splitlines():
        if not 行.strip():
            continue
        try:
            轮 = json.loads(行)
        except json.JSONDecodeError:
            continue
        if isinstance(轮, dict) and 轮.get("问") is not None:
            轮们.append(轮)
    return 轮们[-最多:] if 最多 else 轮们


def _记一轮(目标: dict, 问: str, 答: str, 时间: str) -> None:
    路径 = 对话路径(目标)
    行 = json.dumps({"时间": 时间, "问": 问, "答": 答}, ensure_ascii=False)
    with 路径.open("a", encoding="utf-8") as 文件:
        文件.write(行 + "\n")


# ── 上下文 ───────────────────────────────────────────────────


def _档位分布(证据: dict) -> str:
    名 = {0: "接触", 1: "复现", 2: "产出", 3: "能讲"}
    段 = [f"{名[档]} {len(证据['档'].get(档) or [])} 条" for 档 in (3, 2, 1, 0)]
    return "、".join(段)


def _一条(条目: dict) -> str:
    日期 = (条目.get("when") or "").strip() or 条目["ts"][:10]
    档 = {0: "接触", 1: "复现", 2: "产出", 3: "能讲"}.get(条目["level"], "?")
    行 = f"- {日期}（{档}）：{条目['did']}"
    if 条目.get("blockers"):
        行 += f"　卡在：{'；'.join(条目['blockers'])}"
    return 行


def 组装上下文(目标: dict, *, 证据: dict | None = None) -> str:
    """**只放这个目标的东西**：它自己的字段、它名下的证据、他的底色、你们之前聊过什么。

    为什么故意不放「最近几天别的记录」：那样它就分不清「这个目标卡住了」和
    「他这周在忙别的」——而这两种情况的建议完全不同。要看全局，那是 `life ask` 的事。
    """
    证据 = 证据 or goal.算证据(目标)
    条目们 = sorted(证据["条目们"], key=lambda x: x["ts"], reverse=True)
    段: list[str] = []

    段.append("## 这个目标")
    段.append(f"- 标题：{目标['title']}")
    if 目标.get("why"):
        段.append(f"- 为什么想要它：{目标['why']}")
    段.append(
        f"- 期限：{目标.get('horizon', '')}｜开始 {目标.get('started', '')}"
        f"｜状态 {目标.get('status', '')}"
        + (f"｜截止 {目标['due']}" if 目标.get("due") else "")
    )

    段.append("\n## 这个目标现在的证据（只有他自己的记录，没有别的）")
    if 条目们:
        段.append(
            f"- 共 {证据['条数']} 条，投入约 {证据['分钟'] // 60} 小时，"
            f"最近一次 {证据['最近'] or '无'}"
        )
        段.append(f"- 档位分布：{_档位分布(证据)}")
        段.append("- 最近这几条：")
        段.extend(_一条(条目) for 条目 in 条目们[:10])
    else:
        段.append("（一条都还没有。这个目标还没开始，或记的事没挂到它名下。）")

    段.append("\n## 他的底色（长期是什么样的人，最多 10 行）")
    段.append(_底色())

    旧对话 = 读对话(目标, 最多=最近几轮)
    if 旧对话:
        段.append(f"\n## 你们之前聊过的（最近 {len(旧对话)} 轮）")
        for 轮 in 旧对话:
            段.append(f"- 他问：{轮.get('问', '')}")
            段.append(f"  你说：{(轮.get('答') or '')[:300]}")

    return "\n".join(段)


def _底色() -> str:
    项们 = store.读底色项()
    if not 项们:
        return "（还没攒出来。）"
    行们 = []
    for 项 in 项们[:10]:
        名字 = 项.get("name", "")
        正文 = (项.get("lines") or [""])[0][:60]
        行们.append(f"- {名字}：{正文}")
    return "\n".join(行们)


# ── 问一句 ───────────────────────────────────────────────────


def 问(标识: str, 问题: str) -> dict:
    """带着这个目标的证据问老师一句。返回 {"回答", "token", "条数"}。

    出问题就往上报（llm 的网络/模型错误、目标不存在），由调用方决定怎么说。
    """
    问题 = (问题 or "").strip()
    if not 问题:
        raise ValueError("你还没写要问什么。")

    目标 = goal.找目标(标识)
    证据 = goal.算证据(目标)
    上下文 = 组装上下文(目标, 证据=证据)

    系统提示 = config.prompt文件("goal_chat.md").read_text(encoding="utf-8")
    用户内容 = f"{上下文}\n\n---\n\n他现在问：{问题}"

    回复 = llm.调用("dialogue", 系统提示, 用户内容)
    _记一轮(目标, 问题, 回复.文本.strip(), store.时间文本(store.现在()))
    return {
        "回答": 回复.文本.strip(),
        "token": 回复.输入token + 回复.输出token,
        "条数": 证据["条数"],
    }
