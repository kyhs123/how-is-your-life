"""board.py —— 生成「记录看板」：一个自包含的单个 HTML 文件。

为什么是单文件：
    双击就能用浏览器打开，不需要装软件、不需要联网、不需要起服务。
    把它发给自己（或者三个月后从网盘里翻出来）也还能打开。
    这对应 DESIGN.md §4.8 那句「不引入前端框架，用 Python 字符串模板拼一个自包含 HTML」。

为什么不用现成的图表库：
    任何外链（CDN 上的 JS、字体、图标）都会让这个文件在断网时变成白屏。
    所以图是用 Python 算好坐标、直接写成 SVG 的。

这个文件只读、不改数据。数据来源永远是 vault/now/ 里的 markdown，不是索引。
"""

from __future__ import annotations

import html
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from life import index, store

# 证据档位的中文名（DESIGN.md §3.3）。不做 L0-L3 命名，见术语表。
档位名称 = {0: "接触", 1: "复现", 2: "产出", 3: "能讲"}
部分名称 = {"record": "做过什么", "plan": "想去哪", "emotion": "感受"}
结果名称 = {"done": "做完", "stuck": "卡住", "dropped": "放弃"}


def 生成(输出路径: Path | None = None, *, 含私密: bool = False) -> tuple[Path, dict]:
    """把 vault 里所有记录渲染成一个 HTML 文件。

    返回（文件路径，统计数字）。统计数字给命令行打印用。
    """
    vault = store.确保vault就绪()
    目标 = 输出路径 or (vault / "看板.html")

    全部: list[dict] = []
    读不动的: list[str] = []
    for 路径 in store.遍历条目():
        try:
            全部.append(store.读条目(路径))
        except store.存储错误 as 错误:
            读不动的.append(str(错误))

    显示 = [e for e in 全部 if 含私密 or not e["private"]]
    被藏起来 = len(全部) - len(显示)

    统计 = _算统计(显示)
    统计["读不动的文件"] = 读不动的
    统计["隐去的私密条数"] = 被藏起来

    页面 = _页面(显示, 统计, 含私密=含私密)

    目标.parent.mkdir(parents=True, exist_ok=True)
    临时 = 目标.with_name(目标.name + ".tmp")
    临时.write_text(页面, encoding="utf-8")
    临时.replace(目标)

    return 目标, 统计


# ── 算数字 ───────────────────────────────────────────────────


def _算统计(条目们: list[dict]) -> dict:
    """页面上方那几个数字。全都从记录里数出来，不猜。"""
    档位 = Counter(e["level"] for e in 条目们)
    结果 = Counter(e["outcome"] for e in 条目们)
    部分 = Counter(e["part"] for e in 条目们)
    待看 = sum(1 for e in 条目们 if e["status"] == "needs_review")

    月份们 = sorted({e["ts"][:7] for e in 条目们})
    分钟 = sum(e["minutes"] for e in 条目们)
    锚点 = sum(
        len(e["anchors"]["tech"]) + len(e["anchors"]["people"]) + (1 if e["anchors"]["link"] else 0)
        for e in 条目们
    )

    # 模型花费：从索引的 usage 表读，读不到就当 0（索引可以删，不算错）
    token数 = 0
    调用次数 = 0
    try:
        连接 = index.连接索引()
        try:
            用量 = index.统计(连接)
            token数 = 用量.get("总token", 0)
            调用次数 = 用量.get("调用次数", 0)
        finally:
            连接.close()
    except index.索引错误:
        pass

    return {
        "条数": len(条目们),
        "档位": 档位,
        "结果": 结果,
        "部分": 部分,
        "待看": 待看,
        "月份": 月份们,
        "分钟": 分钟,
        "锚点": 锚点,
        "token": token数,
        "调用": 调用次数,
        "情绪点": 情绪点(条目们),
    }


# ── 拼页面 ───────────────────────────────────────────────────


def _页面(条目们: list[dict], 统计: dict, *, 含私密: bool) -> str:
    """整个 HTML 就这一个字符串。分块拼，方便你自己改样式。"""
    头部 = _头部(统计, 含私密=含私密)
    空状态 = (
        '<p class="empty">还没有任何记录。先敲一条：<code>life add "今天干了什么"</code></p>'
        if not 条目们
        else ""
    )
    正文 = 空状态 + _按月份分组(条目们)
    页脚 = (
        '<footer>这个页面只读。记录本身在 <code>vault/now/</code> 的 markdown 里，'
        "删掉这个 html 不会丢数据。重新生成：<code>life board</code></footer>"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>你过得怎么样 · 记录看板</title>
<style>{_样式()}</style>
</head>
<body>
{头部}
{正文}
{页脚}
</body>
</html>
"""


def _头部(统计: dict, *, 含私密: bool) -> str:
    """页面上方：一句话摘要 + 几个数字 + 档位分布 + 情绪曲线。"""
    月份 = 统计["月份"]
    跨度 = "—" if not 月份 else (月份[0] if len(月份) == 1 else f"{月份[0]} ~ {月份[-1]}")
    小时 = 统计["分钟"] / 60

    摘要 = (
        f"共 <b>{统计['条数']}</b> 条记录 ｜ {span(跨度)} ｜ "
        f"投入约 <b>{小时:.1f}</b> 小时 ｜ 锚点 {统计['锚点']} 个"
    )
    如果算过账 = (
        f" ｜ 模型调用 {统计['调用']} 次，累计 {统计['token']} token" if 统计["调用"] else ""
    )

    提醒 = []
    if 统计["待看"]:
        提醒.append(f'<span class="warn">{统计["待看"]} 条标了 needs_review，需要你确认</span>')
    if 统计["隐去的私密条数"]:
        提醒.append(
            f'<span class="warn">{统计["隐去的私密条数"]} 条私密记录没有显示'
            f"（要看加 <code>--include-private</code>）</span>"
        )
    if 含私密:
        提醒.append('<span class="warn strong">这个页面里包含私密记录，别发给别人</span>')

    return f"""
<header>
  <h1>你过得怎么样</h1>
  <p class="sub">{摘要}{如果算过账}</p>
  <p class="sub">{' '.join(提醒)}</p>
</header>
<section class="stats">
  {_档位条(统计['档位'], 统计['条数'])}
  {_情绪曲线(统计)}
</section>"""


def _档位条(档位: Counter, 总数: int) -> str:
    """证据档分布。用纯 div 画横条，不依赖任何图表库。"""
    if not 总数:
        return ""
    行 = []
    for 档 in (3, 2, 1, 0):
        数 = 档位.get(档, 0)
        宽 = 0 if not 总数 else round(数 / 总数 * 100)
        行.append(
            f'<div class="row"><span class="label">{档位名称[档]}</span>'
            f'<span class="bar"><i class="l{档}" style="width:{宽}%"></i></span>'
            f'<span class="num">{数}</span></div>'
        )
    return '<div class="panel"><h2>证据档位分布</h2>' + "".join(行) + "</div>"


def _情绪曲线(统计: dict) -> str:
    """情绪曲线：按记录顺序画 valence（-1 坏 ~ 1 好）的折线，纯 SVG。"""
    点们 = 统计.get("情绪点") or []
    if len(点们) < 2:
        return (
            '<div class="panel"><h2>情绪曲线</h2>'
            '<p class="empty">记录太少，画不出曲线（至少两条带情绪的记录）。</p></div>'
        )

    宽, 高, 边 = 520, 120, 16
    步 = (宽 - 边 * 2) / (len(点们) - 1)

    def y(值: float) -> float:
        # valence 1（很好）在顶部，-1（很差）在底部
        return 边 + (1 - (值 + 1) / 2) * (高 - 边 * 2)

    折线 = " ".join(
        f"{边 + i * 步:.1f},{y(值):.1f}" for i, (_, 值) in enumerate(点们)
    )
    圆点 = "".join(
        f'<circle cx="{边 + i * 步:.1f}" cy="{y(值):.1f}" r="3" class="{"neg" if 值 < 0 else "pos"}">'
        f"<title>{span(日期)} 情绪 {值:+.1f}</title></circle>"
        for i, (日期, 值) in enumerate(点们)
    )

    return (
        '<div class="panel"><h2>情绪曲线 <small>（左旧右新，越高越好）</small></h2>'
        f'<svg viewBox="0 0 {宽} {高}" preserveAspectRatio="none" class="mood">'
        f'<line x1="{边}" y1="{y(0):.1f}" x2="{宽 - 边}" y2="{y(0):.1f}" class="zero"/>'
        f'<polyline points="{折线}" class="line"/>'
        f"{圆点}"
        "</svg></div>"
    )


def _按月份分组(条目们: list[dict]) -> str:
    """记录卡片，按月份分组、组内新的在上。"""
    分组: dict[str, list[dict]] = defaultdict(list)
    for 条目 in 条目们:
        分组[条目["ts"][:7]].append(条目)

    块 = []
    for 月份 in sorted(分组, reverse=True):
        卡片 = "".join(_卡片(e) for e in sorted(分组[月份], key=lambda x: x["ts"], reverse=True))
        块.append(f'<main><h2 class="month">{span(月份)}</h2>{卡片}</main>')
    return "".join(块)


def _卡片(条目: dict) -> str:
    """一条记录一张卡。"""
    时间 = _短时间(条目["ts"])
    档 = 条目["level"]
    徽章 = [f'<span class="badge l{档}">{档位名称.get(档, "?")}</span>']
    徽章.append(f'<span class="badge plain">{部分名称.get(条目["part"], 条目["part"])}</span>')
    结果 = 结果名称.get(条目["outcome"])
    if 结果 and 条目["outcome"] != "done":
        徽章.append(f'<span class="badge plain">{结果}</span>')
    if 条目["status"] == "needs_review":
        徽章.append('<span class="badge warn">待确认</span>')
    if 条目["private"]:
        徽章.append('<span class="badge private">私密</span>')

    锚点们 = list(条目["anchors"]["tech"]) + list(条目["anchors"]["people"])
    锚点 = ""
    if 锚点们:
        锚点 = '<div class="anchors">' + "".join(
            f"<span>{span(x)}</span>" for x in 锚点们
        ) + "</div>"
    if 条目["anchors"]["link"]:
        链接 = span(条目["anchors"]["link"])
        锚点 += f'<div class="anchors"><span>{链接}</span></div>'

    卡点 = (
        f'<div class="blockers">卡在：{span("；".join(条目["blockers"]))}</div>'
        if 条目["blockers"]
        else ""
    )
    原话 = (
        f"<blockquote>{span(条目['emotion']['quote'])}</blockquote>"
        if 条目["emotion"]["quote"]
        else ""
    )
    花费 = f'<span class="meta">花了 {条目["minutes"]} 分钟</span>' if 条目["minutes"] else ""

    私密类 = " card-private" if 条目["private"] else ""
    return f"""<article class="card{私密类}">
  <div class="when">{时间} {花费}</div>
  <p class="did">{span(条目['did'])}</p>
  <div class="badges">{''.join(徽章)}</div>
  {锚点}
  {卡点}
  {原话}
</article>"""


# ── 小工具 ───────────────────────────────────────────────────


def span(文本: str) -> str:
    """把用户写的字塞进 HTML 之前先转义，免得一个 < 把页面弄坏。"""
    return html.escape(str(文本), quote=True)


def _短时间(ts: str) -> str:
    """2026-11-25T16:43:53+08:00 → 11-25 16:43"""
    try:
        时间 = datetime.fromisoformat(ts)
    except ValueError:
        return span(ts)
    return 时间.strftime("%m-%d %H:%M")


def 情绪点(条目们: list[dict]) -> list[tuple[str, float]]:
    """把记录里带情绪的部分按时间排成一串 (日期, valence)。"""
    点 = [
        (e["ts"][:10], e["emotion"]["valence"])
        for e in sorted(条目们, key=lambda x: x["ts"])
        if e["emotion"]["valence"] != 0 or e["part"] == "emotion"
    ]
    return 点


def _样式() -> str:
    """全部内联。不引用任何外部资源，断网也能看。"""
    return """
:root{
  --纸:#faf8f4; --墨:#22201d; --淡:#7b746c; --线:#e2ddd4; --卡:#fffdf9;
  --接触:#c9c3b8; --复现:#a8b8a0; --产出:#7d9b76; --能讲:#4d6b46;
  --坏:#b5544a; --好:#5c8a52;
}
@media (prefers-color-scheme: dark){
  :root{ --纸:#1b1a18; --墨:#e8e3da; --淡:#9a938a; --线:#332f2b; --卡:#232120;
         --接触:#4a453f; --复现:#4e5d48; --产出:#5f7a59; --能讲:#8fae86;
         --坏:#d0857b; --好:#8dbb82; }
}
*{box-sizing:border-box}
body{margin:0;padding:32px 20px 64px;background:var(--纸);color:var(--墨);
  font:15px/1.7 "Microsoft YaHei","PingFang SC","Hiragino Sans GB",system-ui,sans-serif;
  max-width:760px;margin:0 auto}
h1{font-size:22px;margin:0 0 6px;letter-spacing:.04em}
h2{font-size:14px;margin:0 0 12px;color:var(--淡);font-weight:600;letter-spacing:.08em}
.sub{margin:0 0 4px;color:var(--淡);font-size:13px}
.sub b{color:var(--墨)}
.warn{color:var(--坏)}
.warn.strong{font-weight:700}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:24px 0 8px}
@media (max-width:620px){.stats{grid-template-columns:1fr}}
.panel{background:var(--卡);border:1px solid var(--线);border-radius:10px;padding:14px 16px}
.row{display:flex;align-items:center;gap:10px;margin:4px 0;font-size:13px}
.row .label{width:34px;color:var(--淡)}
.row .bar{flex:1;height:8px;background:var(--线);border-radius:4px;overflow:hidden}
.row .bar i{display:block;height:100%;border-radius:4px}
.row .num{width:22px;text-align:right;color:var(--淡);font-variant-numeric:tabular-nums}
i.l0{background:var(--接触)} i.l1{background:var(--复现)}
i.l2{background:var(--产出)} i.l3{background:var(--能讲)}
.mood{width:100%;height:120px;display:block}
.mood .zero{stroke:var(--线);stroke-dasharray:3 4}
.mood .line{fill:none;stroke:var(--产出);stroke-width:1.6}
.mood .pos{fill:var(--好)} .mood .neg{fill:var(--坏)}
.month{font-size:13px;color:var(--淡);border-bottom:1px solid var(--线);
  padding:22px 0 8px;margin:0 0 14px;letter-spacing:.1em}
.card{background:var(--卡);border:1px solid var(--线);border-left:3px solid var(--产出);
  border-radius:8px;padding:12px 14px;margin:0 0 12px}
.card-private{border-left-color:var(--坏);background:repeating-linear-gradient(
  135deg,var(--卡),var(--卡) 12px,rgba(181,84,74,.06) 12px,rgba(181,84,74,.06) 24px)}
.when{font-size:12px;color:var(--淡);font-variant-numeric:tabular-nums}
.when .meta{margin-left:8px}
.did{margin:6px 0 8px;font-size:16px;line-height:1.6}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
.badge{font-size:11px;padding:1px 7px;border-radius:999px;background:var(--线);color:var(--墨)}
.badge.l3{background:var(--能讲);color:#fff} .badge.l2{background:var(--产出);color:#fff}
.badge.l1{background:var(--复现)} .badge.l0{background:var(--接触)}
.badge.plain{background:transparent;border:1px solid var(--线);color:var(--淡)}
.badge.warn{background:var(--坏);color:#fff}
.badge.private{background:var(--坏);color:#fff}
.anchors{display:flex;flex-wrap:wrap;gap:6px;margin:2px 0 6px}
.anchors span{font-size:12px;color:var(--淡);background:var(--线);padding:1px 6px;border-radius:4px}
.blockers{font-size:13px;color:var(--坏);margin:4px 0}
blockquote{margin:8px 0 2px;padding:4px 10px;border-left:2px solid var(--线);
  color:var(--淡);font-size:13px;font-style:normal}
.empty{color:var(--淡);font-size:13px}
code{background:var(--线);padding:1px 5px;border-radius:4px;font-size:12px}
footer{margin-top:40px;padding-top:14px;border-top:1px solid var(--线);
  color:var(--淡);font-size:12px}
"""
