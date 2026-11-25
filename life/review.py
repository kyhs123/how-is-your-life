"""review.py —— 回顾（DESIGN.md §4.8）。

一段时间的回顾，五块内容：做了什么 / 证据分布变化 / 情绪曲线 / 晋升事件 / 下周一个建议（只给一个）。

两种输出：
    markdown   直接看
    HTML       单文件、双击可看、不引前端框架（和 `life board` 同一套路）

前四块的数据都是**数出来的**，只有「这段日子怎么过的」那段话是模型写的。
模型调不动的时候，回顾照样出得来，只是少了那段话——数据不会因为没网就消失。
"""

from __future__ import annotations

import html
from datetime import date, timedelta

from life import config, index, llm, store

档位名 = {0: "接触", 1: "复现", 2: "产出", 3: "能讲"}


class 回顾错误(Exception):
    """回顾流程里的问题。"""


def 区间(*, 周: bool = True, 季度: bool = False) -> tuple[date, date, str]:
    今天 = store.现在().date()
    if 季度:
        起 = date(今天.year, ((今天.month - 1) // 3) * 3 + 1, 1)
        return 起, 今天, f"{今天.year} 年第 {(今天.month - 1) // 3 + 1} 季度"
    起 = 今天 - timedelta(days=6)
    return 起, 今天, f"{起.isoformat()} ~ {今天.isoformat()}"


def 收集(起: date, 止: date) -> dict:
    """把这段时间的记录、分布、情绪、晋升事件都数出来。"""
    连接 = index.连接索引()
    try:
        行们 = 连接.execute(
            "SELECT id FROM entries WHERE private = 0 AND substr(ts,1,10) BETWEEN ? AND ? ORDER BY ts",
            (起.isoformat(), 止.isoformat()),
        ).fetchall()
        条目们 = [e for e in (index.取条目(连接, 行["id"]) for 行 in 行们) if e]
    finally:
        连接.close()

    天数 = (止 - 起).days + 1
    上起 = 起 - timedelta(days=天数)
    上止 = 起 - timedelta(days=1)
    连接 = index.连接索引()
    try:
        上行 = 连接.execute(
            "SELECT id FROM entries WHERE private = 0 AND substr(ts,1,10) BETWEEN ? AND ?",
            (上起.isoformat(), 上止.isoformat()),
        ).fetchall()
        上段 = [e for e in (index.取条目(连接, 行["id"]) for 行 in 上行) if e]
    finally:
        连接.close()

    段内事件 = [
        行 for 行 in store.读日志()
        if 行[:10] >= 起.isoformat() and 行[:10] <= 止.isoformat()
    ]

    return {
        "起": 起,
        "止": 止,
        "条目们": 条目们,
        "分布": _分布(条目们),
        "上一段分布": _分布(上段),
        "分钟": sum(e["minutes"] for e in 条目们),
        "情绪点": [(e["ts"][:10], e["emotion"]["valence"]) for e in 条目们 if e["emotion"]["valence"]],
        "事件": [行 for 行 in 段内事件 if "晋升" in 行 or "提名" in 行],
    }


def _分布(条目们: list[dict]) -> dict[int, int]:
    结果 = {档: 0 for 档 in (0, 1, 2, 3)}
    for 条目 in 条目们:
        结果[条目["level"]] = 结果.get(条目["level"], 0) + 1
    return 结果


# ── 生成 ─────────────────────────────────────────────────────


def 生成(*, 周: bool = True, 季度: bool = False, 用HTML: bool = False) -> tuple[str, dict]:
    """返回（要输出的文本，统计）。文本是 markdown 或 HTML。"""
    起, 止, 标签 = 区间(周=周, 季度=季度)
    数据 = 收集(起, 止)
    if not 数据["条目们"]:
        raise 回顾错误(f"{标签} 这段时间没有记录，没什么可回顾的。")

    正文, 模型说明 = _用模型写(数据, 标签)

    if 用HTML:
        return _拼HTML(数据, 标签, 正文), 数据
    return _拼markdown(数据, 标签, 正文, 模型说明), 数据


def _用模型写(数据: dict, 标签: str) -> tuple[str, str]:
    """让模型写「这段日子怎么过的」。调不动也不影响回顾本身。"""
    系统提示 = config.prompt文件("review.md").read_text(encoding="utf-8")
    条目摘要 = "\n".join(
        f"- {e['ts'][:10]}（{档位名.get(e['level'], '?')}）：{e['did']}"
        for e in 数据["条目们"][:60]
    )
    用户内容 = (
        f"时间段：{标签}\n"
        f"记录数：{len(数据['条目们'])}，投入约 {数据['分钟'] / 60:.0f} 小时\n"
        f"证据分布：{_分布文字(数据['分布'])}\n"
        f"上一段分布：{_分布文字(数据['上一段分布'])}\n"
        f"晋升事件：{'；'.join(数据['事件']) if 数据['事件'] else '无'}\n\n"
        f"记录：\n{条目摘要}\n"
    )
    try:
        回复 = llm.调用("dialogue", 系统提示, 用户内容, 要JSON=False)
        return 回复.文本.strip(), ""
    except (config.配置错误, llm.模型错误, llm.网络错误) as 错误:
        return "", f"（这次没连上模型，所以只有数据，没有那一段话：{错误}）"


def _分布文字(分布: dict) -> str:
    return " ｜ ".join(f"{档位名[档]} {分布.get(档, 0)}" for 档 in (3, 2, 1, 0))


def _变化文字(现在: dict, 之前: dict) -> str:
    差 = [
        f"{档位名[档]} {现在.get(档, 0) - 之前.get(档, 0):+d}"
        for 档 in (3, 2, 1, 0)
        if 现在.get(档, 0) != 之前.get(档, 0)
    ]
    return "、".join(差) if 差 else "和上一段持平"


def _拼markdown(数据: dict, 标签: str, 正文: str, 模型说明: str) -> str:
    行 = [
        f"# {标签} 的回顾",
        "",
        f"{len(数据['条目们'])} 条记录 ｜ 投入 ~{数据['分钟'] / 60:.0f}h ｜ 晋升 {sum(1 for 行 in 数据['事件'] if '晋升' in 行)} 次",
        "",
        "## 证据分布",
        f"  {_分布文字(数据['分布'])}",
        f"  和上一段比：{_变化文字(数据['分布'], 数据['上一段分布'])}",
        "",
        "## 情绪",
        _情绪文字(数据["情绪点"]),
        "",
    ]
    if 数据["事件"]:
        行 += ["## 晋升事件", *[f"- {行}" for 行 in 数据["事件"]], ""]

    if 正文:
        行 += ["---", "", 正文, ""]
    else:
        行 += ["---", "", 模型说明, ""]

    return "\n".join(行)


def _情绪文字(点们: list[tuple[str, float]]) -> str:
    if len(点们) < 2:
        return "  （带情绪的记录太少，画不出走向）"
    负 = sum(1 for _, 值 in 点们 if 值 < 0)
    正 = sum(1 for _, 值 in 点们 if 值 > 0)
    平均 = sum(值 for _, 值 in 点们) / len(点们)
    return f"  {len(点们)} 条带情绪的记录：负面 {负}、正面 {正}，平均 {平均:+.2f}"


# ── HTML（单文件、无外链）────────────────────────────────────


def _拼HTML(数据: dict, 标签: str, 正文: str) -> str:
    正文HTML = _简易markdown转HTML(正文) if 正文 else "<p class='muted'>这次只有数据。</p>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(标签)} 的回顾</title>
<style>{_样式()}</style>
</head>
<body>
<h1>{html.escape(标签)} 的回顾</h1>
<p class="meta">{len(数据['条目们'])} 条记录 ｜ 投入约 {数据['分钟'] / 60:.0f} 小时</p>

<h2>证据分布</h2>
<p class="meta">{html.escape(_分布文字(数据['分布']))}<br>和上一段比：{html.escape(_变化文字(数据['分布'], 数据['上一段分布']))}</p>

<h2>情绪</h2>
{_情绪SVG(数据['情绪点'])}

{_事件HTML(数据['事件'])}

{正文HTML}

<footer>这个页面只读，不联网、无外链。记录在 vault/now/ 的 markdown 里。</footer>
</body>
</html>
"""


def _事件HTML(事件们: list[str]) -> str:
    if not 事件们:
        return "<h2>晋升事件</h2>\n<p class='meta'>这段时间没有晋升。</p>"
    条目 = "\n".join(f"<li>{html.escape(行)}</li>" for 行 in 事件们)
    return f"<h2>晋升事件</h2>\n<ul>{条目}</ul>"


def _情绪SVG(点们: list[tuple[str, float]]) -> str:
    if len(点们) < 2:
        return "<p class='meta'>（带情绪的记录太少，画不出曲线）</p>"

    宽, 高, 边 = 640, 120, 16
    步 = (宽 - 边 * 2) / (len(点们) - 1)

    def y(值: float) -> float:
        return 边 + (1 - (值 + 1) / 2) * (高 - 边 * 2)

    折线 = " ".join(f"{边 + i * 步:.1f},{y(v):.1f}" for i, (_, v) in enumerate(点们))
    点 = "".join(
        f'<circle cx="{边 + i * 步:.1f}" cy="{y(v):.1f}" r="3" class="{"neg" if v < 0 else "pos"}"/>'
        for i, (_, v) in enumerate(点们)
    )
    return (
        f'<svg viewBox="0 0 {宽} {高}" class="mood">'
        f'<line x1="{边}" y1="{y(0):.1f}" x2="{宽 - 边}" y2="{y(0):.1f}" class="zero"/>'
        f'<polyline points="{折线}" class="line"/>{点}</svg>'
    )


def _简易markdown转HTML(文本: str) -> str:
    """只认 `##` 小标题和 `-` 列表。够用了，不引 markdown 库。"""
    段: list[str] = []
    在列表 = False
    for 行 in 文本.splitlines():
        行 = 行.rstrip()
        if 行.startswith("### "):
            if 在列表:
                段.append("</ul>")
                在列表 = False
            段.append(f"<h3>{html.escape(行[4:])}</h3>")
        elif 行.startswith("## "):
            if 在列表:
                段.append("</ul>")
                在列表 = False
            段.append(f"<h2>{html.escape(行[3:])}</h2>")
        elif 行.startswith("- "):
            if not 在列表:
                段.append("<ul>")
                在列表 = True
            段.append(f"<li>{html.escape(行[2:])}</li>")
        elif not 行.strip():
            if 在列表:
                段.append("</ul>")
                在列表 = False
        else:
            if 在列表:
                段.append("</ul>")
                在列表 = False
            段.append(f"<p>{html.escape(行)}</p>")
    if 在列表:
        段.append("</ul>")
    return "\n".join(段)


def _样式() -> str:
    return """
:root{--纸:#faf8f4;--墨:#22201d;--淡:#7b746c;--线:#e2ddd4;--好:#5c8a52;--坏:#b5544a}
@media (prefers-color-scheme:dark){:root{--纸:#1b1a18;--墨:#e8e3da;--淡:#9a938a;--线:#332f2b;--好:#8dbb82;--坏:#d0857b}}
*{box-sizing:border-box}
body{max-width:760px;margin:0 auto;padding:32px 20px 64px;background:var(--纸);color:var(--墨);
  font:15px/1.75 "Microsoft YaHei","PingFang SC",system-ui,sans-serif}
h1{font-size:22px;margin:0 0 6px}h2{font-size:15px;margin:26px 0 8px;color:var(--淡);letter-spacing:.06em}
h3{font-size:14px;margin:20px 0 6px}
.meta{color:var(--淡);font-size:13px;margin:0 0 8px}
.muted{color:var(--淡)}
ul{padding-left:20px}li{margin:2px 0}
.mood{width:100%;height:120px;display:block;margin:6px 0 12px}
.mood .zero{stroke:var(--线);stroke-dasharray:3 4}
.mood .line{fill:none;stroke:var(--好);stroke-width:1.6}
.mood .pos{fill:var(--好)}.mood .neg{fill:var(--坏)}
footer{margin-top:36px;padding-top:12px;border-top:1px solid var(--线);color:var(--淡);font-size:12px}
"""
