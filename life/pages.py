"""pages.py —— 网页界面的渲染层（docs/WEBUI.md §5.2）。

**这里只做一件事：把准备好的数据变成 HTML。**

硬规矩：这个文件里不许出现 `write_text` / `open` / `sqlite` / `Path`。
所有读写都在 server.py 或更下层完成。这样页面改版时不可能顺手改坏数据。

每个页面是一个纯函数，参数是数据，返回值是完整 HTML。
"""

from __future__ import annotations

import html
import urllib.parse

档位名 = {0: "接触", 1: "复现", 2: "产出", 3: "能讲"}
部分名 = {"record": "做过什么", "plan": "想去哪", "emotion": "感受"}
结果名 = {"done": "做完", "stuck": "卡住", "dropped": "放弃"}
状态名 = {"pending": "待处理", "settled": "已定稿", "needs_review": "待确认"}
目标状态名 = {"active": "进行中", "done": "已完成", "stopped": "已停", "paused": "暂停"}
期限名 = {"short": "短期（2周~1月）", "term": "一学期~半年", "long": "长期（1~3年）"}

导航 = [
    ("/", "今天"),
    ("/entries", "记录"),
    ("/ask", "提问"),
    ("/goals", "目标"),
    ("/chapters", "章节"),
    ("/portrait", "画像"),
    ("/review", "回顾"),
    ("/settings", "设置"),
]


def e(值: object) -> str:
    """转义。页面上所有用户写的内容都必须过这一道。"""
    return html.escape(str(值), quote=True)


def q(值: str) -> str:
    """放进 URL 的那一段。"""
    return urllib.parse.quote(str(值), safe="")


# ── 骨架 ─────────────────────────────────────────────────────


def 布局(标题: str, 内容: str, *, 活跃: str = "", 令牌: str = "") -> str:
    """所有页面共用：导航 + 样式 + 页脚。"""
    链接 = "".join(
        f'<a href="{地址}"{" aria-current=page" if 地址 == 活跃 else ""}>{e(名)}</a>'
        for 地址, 名 in 导航
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="{e(令牌)}">
<title>{e(标题)} · 你过得怎么样</title>
<style>{样式()}</style>
</head>
<body>
<header>
  <p class="brand"><a href="/">你过得怎么样</a></p>
  <nav>{链接}</nav>
</header>
<main>
{内容}
</main>
<footer>
  本机界面 · 只绑 <code>127.0.0.1</code>，别人连不进来 ·
  改的是 <code>vault/</code> 里的 markdown 文件，没有「同步到云」这一步
</footer>
</body>
</html>
"""


# ── 今天 ─────────────────────────────────────────────────────


def 今天(
    令牌: str,
    *,
    待确认数: int,
    最近: list[dict],
    统计: dict,
    提示: str = "",
) -> str:
    块 = [提示块(提示)]

    块.append(
        f"""<section class="记一条">
  <h2>记一条</h2>
  <form method="post" action="/add" enctype="multipart/form-data">
    <input type="hidden" name="token" value="{e(令牌)}">
    <label class="sr" for="text">今天做了什么</label>
    <textarea id="text" name="text" rows="3" maxlength="2000"
      placeholder="今天做了什么？带上具体细节最好，比如：&#10;把 OAuth 调通了，卡在 state 参数签名，调了 4 小时&#10;&#10;只传文件、不写字也可以。"></textarea>
    <p class="file">
      <label for="file">或者传个文件（只传文件不写字也行）</label>
      <input type="file" id="file" name="file"
        accept=".png,.jpg,.jpeg,.webp,.gif,.txt,.md,.docx">
      <span class="hint">图片 png/jpg/webp/gif（≤8MB）· 文档 txt/md/docx（≤8MB）</span>
    </p>
    <p class="checks">
      <label><input type="checkbox" name="emotion" value="1"> 这是感受，不是做了什么</label>
      <label><input type="checkbox" name="private" value="1"> 只存本地（不发给模型）</label>
      <label><input type="checkbox" name="keep" value="1"> 保留原文件（默认只留文字）</label>
    </p>
    <p class="actions"><button type="submit">记下来</button>
      <span class="hint">先落盘，再压缩成一句话。断网也不会丢。</span></p>
  </form>
  <p class="hint">图片会读一遍（OCR 全文留下，原图删掉）；文档会先在本地抽出文字，再压成一句话。</p>
</section>"""
    )

    if 待确认数:
        块.append(
            f'<p class="notice">有 <b>{待确认数}</b> 条记录等你确认 → <a href="/entries?状态=needs_review">去确认</a></p>'
        )

    块.append('<section><h2>最近七天</h2>')
    if 最近:
        块.append('<ul class="流">')
        for 条目 in 最近:
            块.append(
                f'<li><a href="/entries/{q(条目["id"])}">'
                f'<span class="when">{e(条目["ts"][5:16].replace("T", " "))}</span>'
                f'<span class="badge l{条目["level"]}">{档位名.get(条目["level"], "?")}</span>'
                f'{"<span class=\"badge priv\">私密</span>" if 条目["private"] else ""}'
                f'<span class="did">{e(条目["did"])}</span></a></li>'
            )
        块.append("</ul>")
        块.append('<p class="more"><a href="/entries">看全部记录 →</a></p>')
    else:
        块.append(空状态("还没有记录。上面写第一条，十秒钟的事。"))
    块.append("</section>")

    块.append(统计块(统计))
    return 布局("今天", "\n".join(块), 活跃="/", 令牌=令牌)


def 统计块(统计: dict) -> str:
    """一行事实，不做图表、不做百分比。"""
    项 = [
        f"{统计.get('条数', 0)} 条记录",
        f"{统计.get('章节', 0)} 个章节",
        f"{统计.get('目标', 0)} 个目标",
        f"待确认 {统计.get('待看', 0)}",
    ]
    return f'<p class="facts">{"  ·  ".join(e(x) for x in 项)}</p>'


# ── 记录列表 ─────────────────────────────────────────────────


def 记录列表(
    令牌: str,
    *,
    分组: list[tuple[str, list[dict]]],
    筛选: dict,
    页码: int,
    有更早: bool,
    总数: int,
) -> str:
    块 = ['<section><h2>记录 <small>（共 ' + str(总数) + " 条）</small></h2>"]

    # 筛选条：纯链接，不用 JS
    部分链 = "".join(
        _筛选项("/entries", 筛选, "部分", 键, 名)
        for 键, 名 in [("", "全部"), ("record", "做过什么"), ("plan", "想去哪"), ("emotion", "感受")]
    )
    档位链 = "".join(
        _筛选项("/entries", 筛选, "档位", str(键), 名)
        for 键, 名 in [("", "全部"), (0, "接触"), (1, "复现"), (2, "产出"), (3, "能讲")]
    )
    块.append(f'<p class="filters">{部分链}</p><p class="filters">{档位链}</p>')

    if not 分组:
        块.append(空状态("这个条件下没有记录。换个筛选，或者去记一条。"))
    for 月份, 条目们 in 分组:
        块.append(f'<h3 class="month">{e(月份)} <small>{len(条目们)} 条</small></h3>')
        块.append('<ul class="流">')
        for 条目 in 条目们:
            块.append(
                f'<li><a href="/entries/{q(条目["id"])}">'
                f'<span class="when">{e(条目["ts"][5:16].replace("T", " "))}</span>'
                f'<span class="badge l{条目["level"]}">{档位名.get(条目["level"], "?")}</span>'
                f'{"<span class=\"badge priv\">私密</span>" if 条目["private"] else ""}'
                f'{"<span class=\"badge review\">待确认</span>" if 条目["status"] == "needs_review" else ""}'
                f'<span class="did">{e(条目["did"])}</span></a></li>'
            )
        块.append("</ul>")

    翻页 = []
    if 页码 > 1:
        翻页.append(_带参数链接("/entries", 筛选, {"页": 页码 - 1}, "← 更新"))
    if 有更早:
        翻页.append(_带参数链接("/entries", 筛选, {"页": 页码 + 1}, "更早 →"))
    if 翻页:
        块.append(f'<p class="more">{" · ".join(翻页)}</p>')

    块.append("</section>")
    return 布局("记录", "\n".join(块), 活跃="/entries", 令牌=令牌)


def _筛选项(地址: str, 筛选: dict, 键: str, 值: str, 名: str) -> str:
    新 = dict(筛选)
    if 值:
        新[键] = 值
    else:
        新.pop(键, None)
    return _带参数链接(地址, 新, {}, 名, 当前=筛选.get(键, "") == 值)


def _带参数链接(地址: str, 参数: dict, 覆盖: dict, 名: str, 当前: bool = False) -> str:
    合并 = {k: v for k, v in {**参数, **覆盖}.items() if v not in ("", None)}
    查询 = ("?" + urllib.parse.urlencode(合并)) if 合并 else ""
    样式 = ' class="on"' if 当前 else ""
    return f'<a href="{地址}{e(查询)}"{样式}>{e(名)}</a>'


# ── 单条 ─────────────────────────────────────────────────────


def 单条(令牌: str, 条目: dict, *, 错误: str = "", 草稿: dict | None = None) -> str:
    草 = 草稿 or 条目
    块 = [提示块(错误, 是错误=True)]

    块.append(
        f"""<article class="card">
  <p class="when">{e(条目["ts"][:16].replace("T", " "))}
     <span class="badge l{条目["level"]}">{档位名.get(条目["level"], "?")}</span>
     <span class="badge plain">{e(部分名.get(条目["part"], 条目["part"]))}</span>
     <span class="badge plain">{e(状态名.get(条目["status"], 条目["status"]))}</span>
     {"<span class='badge priv'>私密</span>" if 条目["private"] else ""}</p>
  <p class="did big">{e(条目["did"])}</p>
  {_锚点(条目)}
  {_卡点(条目)}
  {f'<blockquote>{e(条目["emotion"]["quote"])}</blockquote>' if 条目["emotion"]["quote"] else ""}
  <p class="meta">情绪 {条目["emotion"]["valence"]:+.1f} ｜ 强度 {条目["emotion"]["arousal"]:.1f}
     {"｜ 花了 " + str(条目["minutes"]) + " 分钟" if 条目["minutes"] else ""}
     {"｜ 章节：" + e(条目["chapter"]) if 条目["chapter"] else ""}</p>
  <p class="meta">目标：{e(条目["goal"]) or "（无）"}</p>
</article>"""
    )

    档位选项 = "".join(
        f'<option value="{值}"{" selected" if 值 == 草["level"] else ""}>{名}</option>'
        for 值, 名 in 档位名.items()
    )
    结果选项 = "".join(
        f'<option value="{值}"{" selected" if 值 == 草["outcome"] else ""}>{名}</option>'
        for 值, 名 in 结果名.items()
    )
    状态选项 = "".join(
        f'<option value="{值}"{" selected" if 值 == 草["status"] else ""}>{名}</option>'
        for 值, 名 in 状态名.items()
    )

    块.append(
        f"""<section>
  <h2>改这一条</h2>
  <form method="post" action="/entries/{q(条目['id'])}" class="form">
    <input type="hidden" name="token" value="{e(令牌)}">
    <label>那句话（≤60 字）
      <input name="did" value="{e(草['did'])}" maxlength="80" required>
    </label>
    <label>档位 <select name="level">{档位选项}</select></label>
    <label>结果 <select name="outcome">{结果选项}</select></label>
    <label>状态 <select name="status">{状态选项}</select></label>
    <p class="actions"><button type="submit">保存</button>
      <a class="btn plain" href="/entries">算了</a></p>
  </form>
  <p class="hint">改的是 <code>vault/now/{e(条目['ts'][:7])}/{e(条目['id'])}.md</code> 里对应的字段。
     私密标记不能在这里改（那会改变隐私承诺）。</p>
</section>"""
    )

    return 布局("单条", "\n".join(块), 活跃="/entries", 令牌=令牌)


def _锚点(条目: dict) -> str:
    锚 = list(条目["anchors"]["tech"]) + list(条目["anchors"]["people"])
    链接 = 条目["anchors"]["link"]
    if not 锚 and not 链接:
        return ""
    项 = "".join(f"<span>{e(x)}</span>" for x in 锚)
    if 链接:
        项 += f"<span>{e(链接)}</span>"
    return f'<p class="anchors">{项}</p>'


def _卡点(条目: dict) -> str:
    if not 条目["blockers"]:
        return ""
    return f'<p class="blockers">卡在：{e("；".join(条目["blockers"]))}</p>'


# ── 提问 ─────────────────────────────────────────────────────


def 提问(
    令牌: str,
    *,
    问题: str,
    召回: list[dict] | None = None,
    回答: str = "",
    诊断: dict | None = None,
    错误: str = "",
    只看召回: bool = False,
) -> str:
    块 = ['<section><h2>提问 <small>（带着你的旧记录回答）</small></h2>']
    块.append(
        f"""<form method="get" action="/ask">
  <label class="sr" for="q">你想问什么</label>
  <input id="q" name="q" value="{e(问题)}" placeholder="比如：我好累，感觉什么都没做成" autofocus>
  <p class="checks">
    <label><input type="checkbox" name="dry" value="1"{" checked" if 只看召回 else ""}> 只看召回，不调模型</label>
  </p>
  <p class="actions"><button type="submit">问</button>
    <span class="hint">要等几秒：它得先翻你的记录。</span></p>
</form>"""
    )
    块.append(提示块(错误, 是错误=True))

    if 回答:
        块.append(f'<article class="card answer"><p>{e(回答).replace(chr(10), "<br>")}</p></article>')

    if 诊断 is not None:
        各路 = 诊断.get("各路", {})
        块.append(
            '<p class="facts">三路命中：'
            + e("、".join(f"{名} {数} 条" for 名, 数 in 各路.items()))
            + "</p>"
        )
        for 提示 in 诊断.get("提示", []):
            块.append(f'<p class="hint">{e(提示)}</p>')

    if 召回:
        块.append('<h3 class="month">翻到的旧记录</h3><ul class="流">')
        for 条目 in 召回:
            块.append(
                f'<li><a href="/entries/{q(条目["id"])}">'
                f'<span class="when">{e(条目["ts"][:10])}</span>'
                f'<span class="badge l{条目["level"]}">{档位名.get(条目["level"], "?")}</span>'
                f'<span class="did">{e(条目["did"])}</span></a></li>'
            )
        块.append("</ul>")
    elif 召回 is not None and not 召回:
        块.append(空状态("一条都没翻到。多记几天，它才有东西可翻。"))

    块.append("</section>")
    return 布局("提问", "\n".join(块), 活跃="/ask", 令牌=令牌)


# ── 目标 ─────────────────────────────────────────────────────


def 目标列表(令牌: str, 目标们: list[dict], 证据们: dict) -> str:
    块 = ['<section><h2>目标</h2>']
    if 目标们:
        块.append('<ul class="目标们">')
        for 目标 in 目标们:
            证据 = 证据们.get(目标["id"]) or {}
            条数 = 证据.get("条数", 0)
            块.append(
                f'<li><a href="/goals/{q(目标["id"])}">'
                f'<span class="title">{e(目标["title"])}</span>'
                f'<span class="tag">{e(目标状态名.get(目标["status"], 目标["status"]))}</span>'
                f'<span class="meta">{条数} 条记录'
                f'{"｜投入 ~" + str(round(证据.get("分钟", 0) / 60)) + "h" if 证据.get("分钟") else ""}</span>'
                f"</a></li>"
            )
        块.append("</ul>")
    else:
        块.append(空状态("还没有目标。想清楚要什么，再立。"))
    块.append('<p class="actions"><a class="btn" href="/goals/new">＋ 新建目标</a></p>')
    块.append(
        '<p class="hint">这里不显示完成度、不标红、不催。'
        "进度看证据，不看百分比。</p>"
    )
    块.append("</section>")
    return 布局("目标", "\n".join(块), 活跃="/goals", 令牌=令牌)


def 目标表单(令牌: str, 目标: dict | None, *, 错误: str = "", 草稿: dict | None = None) -> str:
    新 = 目标 is None
    草 = 草稿 or (目标 if 目标 else {})
    标题 = 草.get("title", "")
    为什么 = 草.get("why", "")
    截止 = 草.get("due", "")
    期限 = 草.get("horizon", "term")
    状态 = 草.get("status", "active")

    期限选项 = "".join(
        f'<option value="{k}"{" selected" if k == 期限 else ""}>{e(v)}</option>'
        for k, v in 期限名.items()
    )
    状态选项 = "".join(
        f'<option value="{k}"{" selected" if k == 状态 else ""}>{e(v)}</option>'
        for k, v in 目标状态名.items()
    )
    动作 = "/goals/new" if 新 else f"/goals/{q(目标['id'])}"

    块 = [
        提示块(错误, 是错误=True),
        f"""<section>
  <h2>{"新建目标" if 新 else "修改目标"}</h2>
  <form method="post" action="{动作}" class="form">
    <input type="hidden" name="token" value="{e(令牌)}">
    <label>标题 <input name="title" value="{e(标题)}" maxlength="60" required></label>
    <label>期限 <select name="horizon">{期限选项}</select></label>
    <label>为什么想要它 <textarea name="why" rows="3" maxlength="300">{e(为什么)}</textarea></label>
    <label>截止日期 <input name="due" value="{e(截止)}" placeholder="2027-01-15"></label>
    <label>状态 <select name="status">{状态选项}</select></label>
    <p class="actions"><button type="submit">{"立这个目标" if 新 else "保存修改"}</button>
      <a class="btn plain" href="/goals">算了</a></p>
  </form>
  <p class="hint">没有「完成度」这一栏——进度不是线性的，百分比是骗人的。</p>
</section>""",
    ]
    return 布局("新建目标" if 新 else "修改目标", "\n".join(块), 活跃="/goals", 令牌=令牌)


def 目标详情(令牌: str, 目标: dict, 证据: dict) -> str:
    """证据卡。只写事实：几条、各档几条、拿得出手的是什么、还缺什么。"""
    行 = []
    摘要 = [f"{证据['条数']} 条记录"]
    if 证据["分钟"]:
        摘要.append(f"投入 ~{发小时(证据['分钟'])}")
    if 证据["最近三天有记录"]:
        摘要.append("最近 3 天活跃")

    行.append(f'<p class="facts">{e(" ｜ ".join(摘要))}</p>')

    if 证据["条数"]:
        行.append('<ul class="档位">')
        for 档 in (3, 2, 1, 0):
            条目们 = 证据["档"].get(档) or []
            if not 条目们:
                continue
            举例 = "、".join(e(x["did"][:26]) for x in 条目们[:3])
            行.append(
                f'<li><span class="badge l{档}">{档位名[档]}</span>'
                f"<b>{len(条目们)}</b> 条 <span class=\"meta\">{举例}</span></li>"
            )
        行.append("</ul>")

        能拿出手 = [x for x in 证据["条目们"] if x["level"] >= 2]
        行.append("<h3>能拿出手的</h3>")
        if 能拿出手:
            行.append('<ul class="流">')
            for 条目 in sorted(能拿出手, key=lambda x: (-x["level"], x["ts"]), )[:5]:
                行.append(
                    f'<li><a href="/entries/{q(条目["id"])}">'
                    f'<span class="when">{e(条目["ts"][:10])}</span>'
                    f'<span class="badge l{条目["level"]}">{档位名[条目["level"]]}</span>'
                    f'<span class="did">{e(条目["did"])}</span></a></li>'
                )
            行.append("</ul>")
        else:
            行.append('<p class="empty">还没有产出或能讲级别的记录。</p>')

        缺 = []
        if not 能拿出手:
            缺.append("以接触为主，缺少独立产出")
        if not (证据["档"].get(3) or []):
            缺.append("还没有「能讲」级别的记录——讲给别人听、或在原场景之外用过")
        if 缺:
            行.append('<p class="blockers">还缺：' + e("；".join(缺)) + "</p>")
    else:
        行.append(
            空状态(
                "还没有记录挂到这个目标上。记录里的 goal 字段要和目标标题对上，才算证据。"
            )
        )

    正文 = f"""<section>
  <h2>{e(目标["title"])}</h2>
  <p class="meta">{e(目标["started"])} → {e(目标状态名.get(目标["status"], 目标["status"]))}
     ｜ {e(期限名.get(目标["horizon"], 目标["horizon"]))}
     {"｜截止 " + e(目标["due"]) if 目标["due"] else ""}</p>
  {'<p class="why">' + e(目标["why"]) + "</p>" if 目标["why"] else ""}
  {''.join(行)}
</section>
<p class="actions"><a class="btn" href="/goals/{q(目标['id'])}/编辑">改这个目标</a>
  <a class="btn plain" href="/goals">回目标列表</a></p>"""

    return 布局(目标["title"], 正文, 活跃="/goals", 令牌=令牌)


def 发小时(分钟: int) -> str:
    return f"{round(分钟 / 60)}h"


# ── 章节 ─────────────────────────────────────────────────────


def 章节列表(令牌: str, 章节们: list[dict]) -> str:
    块 = ['<section><h2>章节 <small>（靠证据晋升上来的主线）</small></h2>']
    if 章节们:
        块.append('<ul class="目标们">')
        for 章节 in 章节们:
            块.append(
                f'<li><a href="/chapters/{q(章节["id"])}">'
                f'<span class="title">{e(章节["title"])}</span>'
                f'<span class="tag">{e(章节["entry_count"])} 条</span>'
                f'<span class="meta">最高 {档位名.get(章节["level_max"], "?")}'
                f'｜最近 {e(章节["last_evidence"])}</span></a></li>'
            )
        块.append("</ul>")
    else:
        块.append(
            空状态("还没有章节。它们在 `life settle` 提名、`life promote` 确认之后才出现。")
        )
    块.append(
        '<p class="hint">章节不是自动生成的：系统提名，你确认。'
        "页面上只看得见结果，生成要回命令行。</p>"
    )
    块.append("</section>")
    return 布局("章节", "\n".join(块), 活跃="/chapters", 令牌=令牌)


def 章节详情(令牌: str, 章节: dict, 条目们: list[dict]) -> str:
    块 = [
        f"""<section>
  <h2>{e(章节["title"])}</h2>
  <p class="meta">{e(章节["started"])} → {e(章节["last_evidence"])}
     ｜ {章节["entry_count"]} 条记录 ｜ 最高 {档位名.get(章节["level_max"], "?")}</p>
  {'<p class="why">' + e(章节["body"]) + "</p>" if 章节["body"] else ""}
</section>"""
    ]
    块.append("<section><h3>它名下的记录</h3>")
    if 条目们:
        块.append('<ul class="流">')
        for 条目 in 条目们:
            块.append(
                f'<li><a href="/entries/{q(条目["id"])}">'
                f'<span class="when">{e(条目["ts"][:10])}</span>'
                f'<span class="badge l{条目["level"]}">{档位名.get(条目["level"], "?")}</span>'
                f'<span class="did">{e(条目["did"])}</span></a></li>'
            )
        块.append("</ul>")
    else:
        块.append(空状态("这个章节名下暂时没有记录。"))
    块.append("</section>")
    return 布局(章节["title"], "\n".join(块), 活跃="/chapters", 令牌=令牌)


# ── 只读文本页（画像 / 回顾）─────────────────────────────────


def 只读文本页(
    令牌: str,
    *,
    标题: str,
    地址: str,
    正文: str,
    命令: str,
    说明: str,
) -> str:
    块 = [
        f'<section><h2>{e(标题)}</h2>',
        f'<p class="hint">{e(说明)}</p>',
        f'<p class="cmd"><code>{e(命令)}</code></p>',
    ]
    if 正文.strip():
        块.append(f'<article class="card text">{_简易markdown(正文)}</article>')
    else:
        块.append(空状态("还没有生成过。回命令行跑上面那条命令，再来这里看。"))
    块.append("</section>")
    return 布局(标题, "\n".join(块), 活跃=地址, 令牌=令牌)


def _简易markdown(文本: str) -> str:
    """只认 ## / ### / - 三种。够画像和回顾用了，不引 markdown 库。"""
    段: list[str] = []
    在列表 = False
    for 行 in 文本.splitlines():
        行 = 行.rstrip()
        if 行.startswith("### "):
            if 在列表:
                段.append("</ul>")
                在列表 = False
            段.append(f"<h4>{e(行[4:])}</h4>")
        elif 行.startswith("## "):
            if 在列表:
                段.append("</ul>")
                在列表 = False
            段.append(f"<h3>{e(行[3:])}</h3>")
        elif 行.startswith("- "):
            if not 在列表:
                段.append("<ul>")
                在列表 = True
            段.append(f"<li>{e(行[2:])}</li>")
        elif not 行.strip():
            if 在列表:
                段.append("</ul>")
                在列表 = False
        else:
            if 在列表:
                段.append("</ul>")
                在列表 = False
            段.append(f"<p>{e(行)}</p>")
    if 在列表:
        段.append("</ul>")
    return "\n".join(段)


# ── 设置 ─────────────────────────────────────────────────────


def 设置(令牌: str, 信息: dict) -> str:
    行 = "".join(
        f"<tr><th>{e(名)}</th><td>{e(值)}</td></tr>" for 名, 值 in 信息["项"]
    )
    块 = [
        '<section><h2>设置</h2>',
        f'<table class="info">{行}</table>',
        '<p class="hint">这里只读。要改配置，编辑 <code>providers.yaml</code> 和 <code>.env</code>，'
        "它们都在 <code>.gitignore</code> 里。</p>",
        "</section>",
    ]
    return 布局("设置", "\n".join(块), 活跃="/settings", 令牌=令牌)


# ── 小零件 ───────────────────────────────────────────────────


def 提示块(文字: str, *, 是错误: bool = False) -> str:
    if not 文字:
        return ""
    类 = "error" if 是错误 else "notice"
    return f'<p class="{类}">{e(文字)}</p>'


def 空状态(文字: str) -> str:
    return f'<p class="empty">{e(文字)}</p>'


def 消息(令牌: str, 标题: str, 说明: str) -> str:
    块 = [
        f"<section><h2>{e(标题)}</h2>",
        f'<p>{e(说明)}</p>',
        '<p class="actions"><a class="btn" href="/">回今天</a></p></section>',
    ]
    return 布局(标题, "\n".join(块), 令牌=令牌)


# ── 样式（docs/WEBUI.md §4：一套变量、一处定义）───────────────


def 样式() -> str:
    return """
:root{
  --纸:#faf8f4; --墨:#22201d; --淡:#7b746c; --线:#e2ddd4; --卡:#fffdf9;
  --点:#7d9b76; --好:#5c8a52; --坏:#b5544a;
  --接触:#c9c3b8; --复现:#a8b8a0; --产出:#7d9b76; --能讲:#4d6b46;
}
@media (prefers-color-scheme: dark){
  :root{ --纸:#1b1a18; --墨:#e8e3da; --淡:#9a938a; --线:#332f2b; --卡:#232120;
    --点:#8fae86; --好:#8dbb82; --坏:#d0857b;
    --接触:#4a453f; --复现:#4e5d48; --产出:#5f7a59; --能讲:#9cc094; }
}
*{box-sizing:border-box}
body{margin:0 auto;max-width:720px;padding:0 18px 64px;background:var(--纸);color:var(--墨);
  font:15px/1.7 "Microsoft YaHei","PingFang SC","Hiragino Sans GB",system-ui,sans-serif;
  -webkit-text-size-adjust:100%}
a{color:var(--能讲)} a:hover{text-decoration:none}
header{padding:22px 0 10px;border-bottom:1px solid var(--线);margin-bottom:22px}
.brand{margin:0 0 8px;font-size:19px;letter-spacing:.04em}
.brand a{color:var(--墨);text-decoration:none}
nav{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:13px}
nav a{color:var(--淡);text-decoration:none;padding:2px 0;border-bottom:2px solid transparent}
nav a:hover{color:var(--墨)}
nav a[aria-current=page]{color:var(--墨);border-bottom-color:var(--点)}
h2{font-size:14px;color:var(--淡);letter-spacing:.06em;margin:26px 0 10px;font-weight:600}
h2 small,h3 small{font-weight:400;letter-spacing:0;color:var(--淡)}
h3{font-size:13px;color:var(--淡);margin:20px 0 8px;letter-spacing:.06em}
h4{font-size:13px;margin:16px 0 6px}
section{margin:0 0 28px}
textarea,input[type=text],input:not([type]),select{width:100%;margin-top:6px;padding:9px 10px;
  font:inherit;color:var(--墨);background:var(--卡);border:1px solid var(--线);border-radius:6px}
textarea{resize:vertical;min-height:72px}
input:focus-visible,textarea:focus-visible,select:focus-visible,button:focus-visible,
a:focus-visible{outline:2px solid var(--点);outline-offset:2px}
form label{display:block;margin:0 0 12px;font-size:13px;color:var(--淡)}
.checks{display:flex;flex-wrap:wrap;gap:16px;margin:10px 0 6px}
.checks label{display:flex;align-items:center;gap:6px;margin:0;font-size:13px;color:var(--淡)}
.checks input{width:auto;margin:0}
.file{margin:14px 0 4px}
.file label{display:block;font-size:13px;color:var(--淡);margin:0 0 6px}
.file input[type=file]{width:100%;padding:8px;font-size:13px;background:var(--卡);
  border:1px dashed var(--线);border-radius:6px;color:var(--淡)}
.file .hint{display:block;margin-top:5px}
.actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:12px 0 0}
button{font:inherit;padding:7px 16px;border-radius:6px;border:1px solid var(--点);
  background:var(--点);color:#fff;cursor:pointer}
button:hover{filter:brightness(1.06)}
.btn{display:inline-block;padding:6px 15px;border-radius:6px;border:1px solid var(--点);
  background:var(--点);color:#fff;text-decoration:none;font-size:14px}
.btn.plain{background:transparent;color:var(--淡);border-color:var(--线)}
.hint{color:var(--淡);font-size:12px;margin:6px 0}
.meta{color:var(--淡);font-size:12.5px;margin:4px 0}
.facts{color:var(--淡);font-size:12.5px;margin:10px 0}
.notice{background:color-mix(in srgb,var(--点) 12%,transparent);border:1px solid var(--线);
  border-radius:8px;padding:10px 12px;font-size:13px;margin:0 0 18px}
.error{color:var(--坏);font-size:13px;border-left:3px solid var(--坏);padding:6px 10px;margin:0 0 14px}
.empty{color:var(--淡);font-size:13px}
.card{background:var(--卡);border:1px solid var(--线);border-radius:8px;padding:14px 16px;margin:0 0 12px}
.card.answer{border-left:3px solid var(--点);font-size:15px;line-height:1.8}
.card.text h3:first-child{margin-top:0}
.did{font-size:15px}
.did.big{font-size:17px;margin:8px 0}
blockquote{margin:10px 0 6px;padding:4px 12px;border-left:2px solid var(--线);color:var(--淡);font-size:13.5px}
.anchors{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.anchors span{font-size:12px;color:var(--淡);background:var(--线);padding:1px 7px;border-radius:4px}
.blockers{color:var(--坏);font-size:13px;margin:8px 0}
.why{font-size:14px;color:var(--墨);border-left:2px solid var(--线);padding-left:12px;margin:10px 0}
.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:999px;
  background:var(--线);color:var(--墨);vertical-align:1px}
.badge.l0{background:var(--接触)} .badge.l1{background:var(--复现)}
.badge.l2{background:var(--产出);color:#fff} .badge.l3{background:var(--能讲);color:#fff}
.badge.plain{background:transparent;border:1px solid var(--线);color:var(--淡)}
.badge.priv{background:transparent;border:1px solid var(--坏);color:var(--坏)}
.badge.review{background:transparent;border:1px dashed var(--线);color:var(--淡)}
ul.流{list-style:none;padding:0;margin:0}
ul.流 li{border-bottom:1px solid var(--线)}
ul.流 li:last-child{border-bottom:none}
ul.流 a{display:flex;gap:8px;align-items:baseline;padding:9px 0;text-decoration:none;color:inherit}
ul.流 a:hover .did{color:var(--能讲)}
ul.流 .when{color:var(--淡);font-size:12px;font-variant-numeric:tabular-nums;min-width:70px}
ul.流 .did{flex:1}
.month{font-size:13px;color:var(--淡);border-bottom:1px solid var(--线);padding:20px 0 8px;margin:0 0 6px}
.filters{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;margin:0 0 8px}
.filters a{color:var(--淡);text-decoration:none}
.filters a.on{color:var(--墨);border-bottom:2px solid var(--点)}
.more{margin:16px 0;font-size:13px}
ul.目标们{list-style:none;padding:0;margin:0}
ul.目标们 li{border-bottom:1px solid var(--线)}
ul.目标们 a{display:block;padding:11px 0;text-decoration:none;color:inherit}
ul.目标们 .title{font-size:15px}
ul.目标们 .tag{float:right;font-size:12px;color:var(--淡);border:1px solid var(--线);
  border-radius:999px;padding:0 8px}
ul.目标们 .meta{display:block;color:var(--淡);font-size:12px}
ul.档位{list-style:none;padding:0;margin:8px 0}
ul.档位 li{padding:6px 0;font-size:13.5px}
ul.档位 .meta{color:var(--淡)}
.cmd code{display:inline-block;background:var(--线);padding:6px 10px;border-radius:6px;font-size:12.5px}
table.info{width:100%;border-collapse:collapse;font-size:13px}
table.info th{text-align:left;color:var(--淡);font-weight:400;padding:7px 10px 7px 0;
  border-bottom:1px solid var(--线);white-space:nowrap;vertical-align:top;width:34%}
table.info td{padding:7px 0;border-bottom:1px solid var(--线);word-break:break-all}
footer{margin-top:40px;padding-top:14px;border-top:1px solid var(--线);color:var(--淡);font-size:12px}
code{background:var(--线);padding:1px 5px;border-radius:4px;font-size:12px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media (max-width:520px){
  body{padding:0 12px 48px}
  ul.流 a{flex-wrap:wrap}
  ul.流 .did{flex-basis:100%}
}
"""
