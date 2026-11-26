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
    ("/chapters", "主题"),
    ("/portrait", "画像"),
    ("/export", "导出"),
    ("/settings", "设置"),
]


def e(值: object) -> str:
    """转义。页面上所有用户写的内容都必须过这一道。"""
    return html.escape(str(值), quote=True)


def q(值: str) -> str:
    """放进 URL 的那一段。"""
    return urllib.parse.quote(str(值), safe="")


# ── 骨架 ─────────────────────────────────────────────────────


def 布局(
    标题: str, 内容: str, *, 活跃: str = "", 令牌: str = "", 自刷秒数: int = 0
) -> str:
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
{"<meta http-equiv=\"refresh\" content=\"" + str(自刷秒数) + "\">" if 自刷秒数 else ""}
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
  只绑 <code>127.0.0.1</code> · 改的是 <code>vault/</code> 里的 markdown · 没有「同步到云」这一步
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
    待抽取数: int = 0,
) -> str:
    块 = [提示块(提示)]

    块.append(
        f"""<section class="记一条">
  <h2>记一条</h2>
  <form method="post" action="/add" enctype="multipart/form-data">
    <input type="hidden" name="token" value="{e(令牌)}">
    <label class="when">什么时候
      <input name="when" maxlength="24"
        placeholder="不填就是现在；以前的事可以写 2023 / 2023-09 / 大一">
    </label>
    <label class="sr" for="text">做了什么</label>
    <textarea id="text" name="text" rows="4" maxlength="4000"
      placeholder="做了什么？细节写得越具体越好，比如：&#10;把 OAuth 调通了，卡在 state 参数签名，调了 4 小时"></textarea>
    <p class="hint 写什么">写以前做过的项目也行——<b>做了什么、用了什么、卡在哪、怎么解决</b>。
      日期记不清就空着，或者写「大一」。</p>
    <p class="file">
      <label for="file">或者传个文件（只传文件、不写字也行）</label>
      <input type="file" id="file" name="file"
        accept=".png,.jpg,.jpeg,.webp,.gif,.txt,.md,.docx">
      <span class="hint">图片 png/jpg/webp/gif ｜ 文档 txt/md/docx ｜ 每个 ≤8MB ｜ 图片读完只留文字，原图删掉</span>
    </p>
    <p class="checks">
      <label><input type="checkbox" name="emotion" value="1"> 这是感受，不是做了什么</label>
      <label><input type="checkbox" name="private" value="1"> 只存本地（不发给模型）</label>
      <label><input type="checkbox" name="keep" value="1"> 保留原文件（默认只留文字）</label>
    </p>
    <p class="actions"><button type="submit">记下来</button></p>
  </form>
</section>"""
    )

    if 待抽取数:
        块.append(
            f'<p class="notice">有 <b>{待抽取数}</b> 条还没抽成（当时断了网或模型出错）。'
            + 作业按钮(令牌, "retry", "补抽", 次要=True)
            + "</p>"
        )

    if 待确认数:
        块.append(
            f'<p class="notice">有 <b>{待确认数}</b> 条记录等你确认 → '
            f'<a href="/entries?状态=needs_review">去确认</a>'
            " ｜ "
            '<form method="post" action="/entries/settle-all" class="inline">'
            f'<input type="hidden" name="token" value="{e(令牌)}">'
            '<button type="submit" class="btn plain">全部确认</button></form></p>'
        )

    块.append('<section><h2>最近七天</h2>')
    if 最近:
        块.append('<ul class="流">')
        for 条目 in 最近:
            块.append(
                f'<li><a href="/entries/{q(条目["id"])}">'
                f'<span class="when">{e(条目.get("when") or 条目["ts"][5:16].replace("T", " "))}</span>'
                f'<span class="did">{e(条目["did"])}</span>'
                f'<span class="badge l{条目["level"]}">{档位名.get(条目["level"], "?")}</span>'
                f'{"<span class=\"badge priv\">私密</span>" if 条目["private"] else ""}'
                "</a></li>"
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
        f"{统计.get('章节', 0)} 个主题",
        f"{统计.get('目标', 0)} 个目标",
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
    块 = [f'<section><h2>记录<small>共 {总数} 条</small></h2>']

    # 筛选条：纯链接，不用 JS
    部分链 = "".join(
        _筛选项("/entries", 筛选, "部分", 键, 名)
        for 键, 名 in [("", "全部"), ("record", "做过什么"), ("plan", "想去哪"), ("emotion", "感受")]
    )
    档位链 = "".join(
        _筛选项("/entries", 筛选, "档位", str(键), 名)
        for 键, 名 in [("", "全部"), (0, "接触"), (1, "复现"), (2, "产出"), (3, "能讲")]
    )
    块.append(
        f'<p class="filters"><span>类型</span>{部分链}</p>'
        f'<p class="filters"><span>档位</span>{档位链}</p>'
    )
    if 筛选.get("状态") == "needs_review":
        块.append(
            '<p class="notice">现在只显示「待确认」的记录。'
            f'<a href="/entries">看全部</a>'
            " ｜ "
            '<form method="post" action="/entries/settle-all" class="inline">'
            f'<input type="hidden" name="token" value="{e(令牌)}">'
            '<button type="submit" class="btn plain">全部确认</button></form></p>'
        )

    if not 分组:
        块.append(空状态("这个条件下没有记录。换个筛选，或者去记一条。"))
    for 月份, 条目们 in 分组:
        块.append(f'<h3 class="month">{e(月份)} <small>{len(条目们)} 条</small></h3>')
        块.append('<ul class="流">')
        for 条目 in 条目们:
            块.append(
                f'<li><a href="/entries/{q(条目["id"])}">'
                f'<span class="when">{e(条目.get("when") or 条目["ts"][5:16].replace("T", " "))}</span>'
                f'<span class="did">{e(条目["did"])}</span>'
                f'<span class="badge l{条目["level"]}">{档位名.get(条目["level"], "?")}</span>'
                f'{"<span class=\"badge priv\">私密</span>" if 条目["private"] else ""}'
                f'{"<span class=\"badge review\">待确认</span>" if 条目["status"] == "needs_review" else ""}'
                "</a></li>"
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
  <p class="when">{e(条目.get("when") or 条目["ts"][:16].replace("T", " "))}
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
     {"｜ 主题：" + e(条目["chapter"]) if 条目["chapter"] else ""}</p>
  {f'<p class="meta">目标：{e(条目["goal"])}</p>' if 条目["goal"] else ""}
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
    <label>什么时候（人话就行，比如 大一 / 2023-09；留空=不详）
      <input name="when" value="{e(草.get('when', ''))}" maxlength="40">
    </label>
    <label>档位 <select name="level">{档位选项}</select></label>
    <label>结果 <select name="outcome">{结果选项}</select></label>
    <label>状态 <select name="status">{状态选项}</select></label>
    <p class="actions"><button type="submit">保存</button>
      <a class="btn plain" href="/entries">算了</a></p>
  </form>
  <p class="hint">改的是 <code>vault/now/{e(条目['ts'][:7])}/{e(条目['id'])}.md</code>。私密标记不在这儿改。</p>
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
    没做到: list[str] | None = None,
) -> str:
    块 = ['<section><h2>提问<small>带着你的旧记录回答</small></h2>']
    块.append(
        f"""<form method="get" action="/ask">
  <label class="sr" for="q">你想问什么</label>
  <input id="q" name="q" value="{e(问题)}" placeholder="比如：我好累，感觉什么都没做成">
  <p class="checks">
    <label><input type="checkbox" name="dry" value="1"{" checked" if 只看召回 else ""}> 只看召回，不调模型</label>
  </p>
  <p class="actions"><button type="submit">问</button>
    <span class="hint">要等几秒：它得先翻你的记录。</span></p>
</form>"""
    )
    块.append(提示块(错误, 是错误=True))

    if 回答:
        块.append(f'<article class="card answer">{_多段(回答)}</article>')

    # 这句是「我这边没达标」的提示，属于系统消息，**不能混进回答正文**（踩过）
    if 没做到:
        块.append(
            '<p class="error">这次回答有几条硬要求没做到（已经重试过一次，不是你的错）：<br>'
            + "<br>".join(f"· {e(一条)}" for 一条 in 没做到)
            + "</p>"
        )

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
                f'<span class="when">{e((条目.get("when") or "").strip() or 条目["ts"][:10])}</span>'
                f'<span class="did">{e(条目["did"])}</span>'
                f'<span class="badge l{条目["level"]}">{档位名.get(条目["level"], "?")}</span>'
                "</a></li>"
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
    块.append('<p class="hint">不显示完成度、不催 —— 进度看证据。</p>')
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
</section>""",
    ]
    return 布局("新建目标" if 新 else "修改目标", "\n".join(块), 活跃="/goals", 令牌=令牌)


def 目标详情(
    令牌: str,
    目标: dict,
    证据: dict,
    *,
    对话: list[dict] | None = None,
    提示: str = "",
    提示是错误: bool = False,
) -> str:
    """证据卡 + 问老师 + 这个目标自己的记一条。

    证据卡的规矩没变：只写事实（几条、各档几条、拿得出手的、还缺什么），不打分、不给百分比。
    底下两块都是「把下一步变小」的工具：
      - **问老师**：带着这个目标的证据问 AI。它只看得见这个目标，所以不会泛泛而谈。
      - **记一条**：记完 `goal` 直接写成目标标题，立刻变成证据。
    """
    行 = []
    if 提示:
        行.append(提示块(提示, 是错误=提示是错误))
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
                    f'<span class="when">{e((条目.get("when") or "").strip() or 条目["ts"][:10])}</span>'
                    f'<span class="did">{e(条目["did"])}</span>'
                    f'<span class="badge l{条目["level"]}">{档位名[条目["level"]]}</span>'
                    "</a></li>"
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
        行.append(空状态("还没有记录。下面写一条，就是它的证据。"))

    行.append(问老师块(令牌, 目标, 对话 or []))

    行.append(
        f"""<section class="记一条">
  <h2>往「{e(目标["title"])}」里记一条</h2>
  <form method="post" action="/add" enctype="multipart/form-data">
    <input type="hidden" name="token" value="{e(令牌)}">
    <input type="hidden" name="goal" value="{e(目标["title"])}">
    <input type="hidden" name="back" value="/goals/{q(目标["id"])}">
    <label class="when">什么时候
      <input name="when" maxlength="24"
        placeholder="不填就是现在；以前的事可以写 大一 / 2023-09">
    </label>
    <label class="sr" for="goal-text">为这个目标做了什么</label>
    <textarea id="goal-text" name="text" rows="3" maxlength="4000"
      placeholder="为这个目标做了什么？一句话就够，细节越具体越好。比如：&#10;投了 3 家实习，第 2 家做完笔试"></textarea>
    <p class="file">
      <label for="goal-file">或者传个文件（简历、截图、笔记；只传文件也行）</label>
      <input type="file" id="goal-file" name="file"
        accept=".png,.jpg,.jpeg,.webp,.gif,.txt,.md,.docx">
    </p>
    <p class="checks">
      <label><input type="checkbox" name="private" value="1"> 只存本地（不发给模型）</label>
      <label><input type="checkbox" name="keep" value="1"> 保留原文件</label>
    </p>
    <p class="actions"><button type="submit">记到这个目标里</button></p>
  </form>
</section>"""
    )

    正文 = f"""<section>
  <h1>{e(目标["title"])}</h1>
  <p class="meta">{e(目标["started"])} → {e(目标状态名.get(目标["status"], 目标["status"]))}
     ｜ {e(期限名.get(目标["horizon"], 目标["horizon"]))}
     {"｜截止 " + e(目标["due"]) if 目标["due"] else ""}</p>
  {'<p class="why">' + e(目标["why"]) + "</p>" if 目标["why"] else ""}
  {''.join(行)}
</section>
<p class="actions"><a class="btn" href="/goals/{q(目标['id'])}/编辑">改这个目标</a>
  <a class="btn plain" href="/goals">回目标列表</a></p>"""

    return 布局(目标["title"], 正文, 活跃="/goals", 令牌=令牌)


def 问老师块(令牌: str, 目标: dict, 对话: list[dict]) -> str:
    """「问老师」：对话框 + 三个一键问题。

    为什么给一键问题：大多数时候人不知道该问什么，只会说「我该怎么办」。
    点一下「我该从哪开始」，比让他先想出一个好问题容易得多。
    """
    地址 = f"/goals/{q(目标['id'])}/chat"
    快问 = "".join(
        f'<form method="post" action="{地址}" class="inline">'
        f'<input type="hidden" name="token" value="{e(令牌)}">'
        f'<input type="hidden" name="q" value="{e(问)}">'
        f'<button type="submit" class="plain">{e(问)}</button></form>'
        for 问 in ("我该从哪开始？", "接下来一周做什么？", "我卡住了，帮我拆一下")
    )

    历史 = []
    for 轮 in 对话[-3:]:
        历史.append(f'<p class="问">我：{e(轮.get("问", ""))}</p>')
        历史.append(f'<article class="card answer">{_多段(轮.get("答", ""))}</article>')

    return f"""<section>
  <h2>问老师<small>它只看这个目标的证据</small></h2>
  {''.join(历史) if 历史 else 空状态("还没聊过。问一句试试——点下面的一键问题最省事。")}
  <div class="快问">{快问}</div>
  <form method="post" action="{地址}" class="form">
    <input type="hidden" name="token" value="{e(令牌)}">
    <label class="sr" for="goal-q">想问什么</label>
    <textarea id="goal-q" name="q" rows="2" maxlength="600"
      placeholder="想怎么推进这个目标？比如：我该从哪开始"></textarea>
    <p class="actions"><button type="submit">问老师</button>
      <span class="hint">要等十来秒：它先把证据读一遍再答。</span></p>
  </form>
</section>"""


def 发小时(分钟: int) -> str:
    return f"{round(分钟 / 60)}h"


# ── 章节 ─────────────────────────────────────────────────────


def 章节列表(
    令牌: str, 章节们: list[dict], 提名们: list[dict] | None = None
) -> str:
    提名们 = 提名们 or []
    块 = [
        '<section><h2>主题</h2>'
        '<p class="hint">你真正在忙的那些事：系统把同一件事的记录串成一条线，提名给你，认不认由你。</p>'
        '<p class="hint">目标是<em>你想做成什么</em>，主题是<em>你实际在忙什么</em>。</p>'
        "</section>"
    ]

    if 提名们:
        块.append('<h3>等你确认的提名</h3>')
        for 提名 in 提名们:
            标题 = 提名.get("标题", "")
            块.append(
                f"""<article class="card">
  <p class="did"><b>{e(标题)}</b></p>
  <p class="meta">{e(提名.get("摘要", ""))}</p>
  <p class="meta">{提名.get("条数", 0)} 条记录 ｜ 跨 {'、'.join(提名.get("月份", []))}</p>
  <div class="actions">
    <form method="post" action="/promotions/{q(标题)}/yes" class="inline">
      <input type="hidden" name="token" value="{e(令牌)}">
      <button type="submit">要</button>
    </form>
    <form method="post" action="/promotions/{q(标题)}/no" class="inline">
      <input type="hidden" name="token" value="{e(令牌)}">
      <button type="submit" class="plain">不要</button>
    </form>
  </div>
</article>"""
            )
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
            空状态(
                "还没有主题。它们是系统归纳出来、经你确认之后才出现的"
                "（点下面的按钮归纳一次试试）。"
            )
        )
    块.append(
        '<p class="actions">'
        + 作业按钮(
            令牌, "settle", "归纳一次", 说明="只写提名，不动你的记录", 次要=True
        )
        + "</p>"
    )
    块.append("</section>")
    return 布局("主题", "\n".join(块), 活跃="/chapters", 令牌=令牌)


def 章节详情(令牌: str, 章节: dict, 条目们: list[dict]) -> str:
    块 = [
        f"""<section>
  <h1>{e(章节["title"])}</h1>
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
                f'<span class="when">{e((条目.get("when") or "").strip() or 条目["ts"][:10])}</span>'
                f'<span class="did">{e(条目["did"])}</span>'
                f'<span class="badge l{条目["level"]}">{档位名.get(条目["level"], "?")}</span>'
                "</a></li>"
            )
        块.append("</ul>")
    else:
        块.append(空状态("这个主题名下暂时没有记录。"))
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
    按钮: str = "",
) -> str:
    块 = [
        f'<section><h2>{e(标题)}</h2>',
        f'<p class="hint">{e(说明)}</p>',
        f'<p class="actions">{按钮}</p>' if 按钮 else "",
        f'<p class="hint">命令行等价：<code>{e(命令)}</code></p>',
    ]
    if 正文.strip():
        块.append(f'<article class="card text">{_简易markdown(正文)}</article>')
    else:
        块.append(空状态("还没有生成过。点上面的按钮生成，一两分钟后回来看。"))
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
        elif 行.startswith("# "):
            # 导出物里的 `#` 是「这是谁」——简历的名字，要能一眼看见
            if 在列表:
                段.append("</ul>")
                在列表 = False
            段.append(f'<p class="大标题">{e(行[2:])}</p>')
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
        elif 行.startswith("> "):
            if 在列表:
                段.append("</ul>")
                在列表 = False
            段.append(f'<p class="notice">{e(行[2:])}</p>')
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


# ── 导出 ─────────────────────────────────────────────────────


def 导出页(
    令牌: str,
    模板名们: list[str],
    *,
    上次们: list[dict] | None = None,
    提示: str = "",
    草稿: str = "",
) -> str:
    """一句话 + 一个模板，导出成能直接用的文件。

    模板默认「自动认」——大多数人不会先想「我该选哪个模板」，
    他们会直接说「我要应聘机器人相关的工作」。
    """
    上次们 = 上次们 or []
    选项 = '  <option value="">自动认（从你那句话里判断）</option>'
    选项 += "".join(f'  <option value="{e(名)}">{e(名)}</option>' for 名 in 模板名们)

    列表 = []
    for 文件 in 上次们[:8]:
        列表.append(
            f'<li><a href="/exports/{q(文件["名字"])}">'
            f'<span class="when">{e(文件["时间"])}</span>'
            f'<span class="did">{e(文件["名字"])}</span></a></li>'
        )

    正文 = f"""<section>
  <h2>导出<small>把记录变成能直接用的东西</small></h2>
  {提示块(提示, 是错误=bool(提示))}
  <p class="hint 说明">说清你要什么就行：给谁看、什么方向、多长。它只挑拿得出手的记录，
    记录里没有的会留成「（待补：…）」，不会替你编。</p>
  <form method="post" action="/export" class="form">
    <input type="hidden" name="token" value="{e(令牌)}">
    <label>你要什么
      <textarea name="要求" rows="3" maxlength="600"
        placeholder="比如：我要应聘机器人相关的工作，帮我生成一份简历">{e(草稿)}</textarea>
    </label>
    <label>模板 <select name="模板">{选项}</select></label>
    <p class="actions"><button type="submit">导出</button>
      <span class="hint">要跑二三十秒：它得先挑素材再写。跑完回这一页。</span></p>
  </form>
  <p class="hint">命令行等价：<code>life export "…"</code>（加 <code>--dry-run</code> 只看挑了什么素材）</p>
</section>
<section>
  <h3>导过的</h3>
  {'<ul class="流">' + ''.join(列表) + '</ul>' if 列表 else 空状态('还没导出过。')}
</section>"""
    return 布局("导出", 正文, 活跃="/export", 令牌=令牌)


def 导出物(令牌: str, 名字: str, 正文: str) -> str:
    """看一份导出物。

    markdown 的按段落渲染出来（直接显示 `##` 和 `-` 太丑），原文件随时能下载。
    开头那行 `<!-- 由 life export 生成 -->` 是给人和工具看的元信息，显示时去掉。
    """
    行们 = [行 for 行 in 正文.splitlines() if not 行.strip().startswith("<!--")]
    显示 = "\n".join(行们).strip()
    内容 = (
        _简易markdown(显示)
        if 名字.endswith(".md")
        else "".join(f"<p>{e(段)}</p>" for 段 in 显示.split("\n\n") if 段.strip())
    )
    块 = [
        f"<section><h2>{e(名字)}</h2>",
        '<p class="actions"><a class="btn plain" '
        f'href="/exports/{q(名字)}?raw=1">下载原文件</a>'
        '<a class="btn plain" href="/export">回导出</a></p>',
        f'<article class="card text 导出">{内容}</article></section>',
    ]
    return 布局(名字, "\n".join(块), 活跃="/export", 令牌=令牌)


# ── 设置 ─────────────────────────────────────────────────────


def 设置(令牌: str, 信息: dict, 按钮: str = "") -> str:
    行 = "".join(
        f"<tr><th>{e(名)}</th><td>{e(值)}</td></tr>" for 名, 值 in 信息["项"]
    )
    块 = [
        '<section><h2>设置</h2>',
        f'<table class="info">{行}</table>',
        f'<p class="actions">{按钮}</p>' if 按钮 else "",
        '<p class="hint">这里只读。要改配置，编辑 <code>providers.yaml</code> 和 <code>.env</code>，'
        "它们都在 <code>.gitignore</code> 里。</p>",
        "</section>",
    ]
    return 布局("设置", "\n".join(块), 活跃="/settings", 令牌=令牌)


# ── 后台任务（docs/WEBUI.md §2.6）────────────────────────────


def 作业按钮(令牌: str, 动作: str, 标签: str, *, 说明: str = "", 次要: bool = False) -> str:
    """一个能起后台任务的按钮。"""
    类 = "btn plain" if 次要 else "btn"
    return (
        f'<form method="post" action="/jobs/{q(动作)}" class="inline">'
        f'<input type="hidden" name="token" value="{e(令牌)}">'
        f'<button type="submit" class="{类}">{e(标签)}</button></form>'
        + (f'<span class="hint"> {e(说明)}</span>' if 说明 else "")
    )


def 任务页(令牌: str, 任务) -> str:
    """后台任务的进度页。跑着就自刷，跑完显示结果。"""
    秒 = int(任务.用了多少秒)
    块 = [f"<section><h2>{e(任务.名称)}</h2>"]

    if 任务.状态 == "running":
        块.append(
            f'<p class="facts">正在跑 · 已经 {秒} 秒'
            f"{' · 这类活一般要一两分钟' if 秒 < 60 else ''}</p>"
        )
        块.append(
            '<p class="hint">每 3 秒自动刷新。可以去做别的，关掉页面不会中断任务。</p>'
        )
    elif 任务.状态 == "failed":
        块.append(pages_错误(任务.错误))
        块.append('<p class="actions">' + 作业按钮(令牌, 任务.动作, "重试") + "</p>")
    else:
        块.append(f'<p class="facts">完成 · 用了 {秒} 秒</p>')
        块.append(f'<p>{e(任务.结果)}</p>')
        if 任务.去向:
            块.append(
                f'<p class="actions"><a class="btn" href="{e(任务.去向)}">去看看</a>'
                f'<a class="btn plain" href="/">回今天</a></p>'
            )
    块.append("</section>")
    return 布局(
        任务.名称, "\n".join(块), 令牌=令牌, 自刷秒数=3 if 任务.状态 == "running" else 0
    )


def pages_错误(文字: str) -> str:
    return f'<p class="error">{e(文字)}</p>'



# ── 小零件 ───────────────────────────────────────────────────


def 提示块(文字: str, *, 是错误: bool = False) -> str:
    if not 文字:
        return ""
    类 = "error" if 是错误 else "notice"
    return f'<p class="{类}">{e(文字)}</p>'


def 空状态(文字: str) -> str:
    return f'<p class="empty">{e(文字)}</p>'


def _多段(文字: str) -> str:
    """模型说的话 → 段落。

    空行分段（每段一个 <p>，段间距由 CSS 给），段内单换行留 <br>。
    直接 `\\n` 全换 <br> 会在空行处出现两倍行距，读起来散。
    """
    段们 = [段.strip() for 段 in str(文字 or "").split("\n\n") if 段.strip()]
    if not 段们:
        return "<p></p>"
    return "".join(f"<p>{e(段).replace(chr(10), '<br>')}</p>" for 段 in 段们)


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
/* ── 字与色 ────────────────────────────────────────────────────
   2026-11-26 第二次重做。两条硬规矩：
   1. 字体栈里只写这台机器上真的有的字（查过字体表：Noto Sans/Serif SC、Consolas、
      Cascadia Mono 有；Microsoft YaHei、PingFang SC、SimSun、IBM Plex Mono 都没有）
   2. 字号阶梯拉开到 12 / 14 / 16.5 / 20 / 28 / 32，相邻差 ≥20%——
      原来 15/16/19 挤在一起，标题看着像加粗的正文 */
:root{
  /* 亮色：森林墨 */
  --纸:#f5f1e8; --纸2:#eae3d4;
  --墨:#1a2e1f; --墨柔:#43523f; --墨淡:#6b7566;
  --线:#d5ccba; --线强:#a89c85; --线淡:#e3dccd;
  --点:#2e6b4f; --点上的字:#f5f1e8;
  --坏:#8c3f36;
  --档0:#a9a294; --档1:#8aa88f; --档2:#4f7f60; --档3:#2e6b4f;
  --箭头:#6b7566;

  --无衬线:"Noto Sans SC","Microsoft YaHei",system-ui,-apple-system,"Segoe UI",sans-serif;
  --衬线:"Noto Serif SC","Source Han Serif SC",Georgia,serif;
  --等宽:"Cascadia Mono",Consolas,ui-monospace,monospace;  /* 只给代码和文件名 */
}
@media (prefers-color-scheme:dark){
  :root{
    /* 暗色：午夜墨 */
    --纸:#12110f; --纸2:#1c1a17;
    --墨:#efe5d3; --墨柔:#cfc3ad; --墨淡:#9b9081;
    --线:#332e28; --线强:#4f473c; --线淡:#262220;
    --点:#d9a458; --点上的字:#1a1206;
    --坏:#cf9084;
    --档0:#6b6357; --档1:#86987f; --档2:#b6c8ab; --档3:#e3b166;
    --箭头:#9b9081;
  }
}

*{box-sizing:border-box}
body{margin:0 auto;max-width:600px;padding:0 24px 80px;background:var(--纸);color:var(--墨);
  font:16.5px/1.85 var(--无衬线);-webkit-text-size-adjust:100%}
p{margin:0 0 1.05em}
a{color:var(--点);text-decoration:none;text-underline-offset:.22em}
a:hover{text-decoration:underline}
a:focus-visible,button:focus-visible,.btn:focus-visible{outline:2px solid var(--点);outline-offset:2px}

/* ── 页头：品牌用衬线（28px 才立得住），导航用无衬线小字 ── */
header{padding:40px 0 0;margin:0 0 44px}
.brand{margin:0 0 20px;font:500 28px/1.25 var(--衬线);letter-spacing:.01em}
.brand a{color:var(--墨)}
.brand a:hover{text-decoration:none}
nav{display:flex;flex-wrap:wrap;gap:24px;padding:0 0 13px;
  font:400 12px/1 var(--无衬线);letter-spacing:.08em;border-bottom:1px solid var(--线强)}
nav a{color:var(--墨淡);padding-bottom:13px;margin-bottom:-13px;border-bottom:2px solid transparent}
nav a:hover{color:var(--墨);text-decoration:none}
nav a[aria-current=page]{color:var(--墨);border-bottom-color:var(--点)}

/* ── 分区与标题 ── */
section{margin:0 0 48px}
h1{margin:0 0 18px;font:500 32px/1.32 var(--衬线);letter-spacing:.01em}
h2{margin:0 0 14px;font:500 20px/1.5 var(--无衬线);letter-spacing:.01em}
h2 small{margin-left:10px;font:400 12px/1.4 var(--无衬线);letter-spacing:.02em;color:var(--墨淡)}
h3{margin:0 0 10px;font:500 14px/1.5 var(--无衬线);letter-spacing:.02em;color:var(--墨柔)}
h4{margin:24px 0 8px;font:500 16.5px/1.6 var(--无衬线)}

/* ── 表单：标签比提示亮，输入框描边看得见 ── */
label{display:block;margin:0 0 18px;font-size:12.5px;color:var(--墨柔)}
input,textarea,select{width:100%;margin-top:8px;padding:12px 14px;font:16px/1.6 var(--无衬线);
  color:var(--墨);background:var(--纸);border:1px solid var(--线强);border-radius:3px}
textarea{min-height:104px;resize:vertical}
::placeholder{color:var(--墨淡);opacity:.6;font-size:15px}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--点);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--点) 16%,transparent)}

/* 下拉箭头自己画：原生的在暗色下是白三角 */
select{appearance:none;padding-right:40px;background-repeat:no-repeat;
  background-position:right 15px center;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='8'><path d='M1 1l5 5 5-5' fill='none' stroke='%236b7566' stroke-width='1.6' stroke-linecap='round'/></svg>")}
@media (prefers-color-scheme:dark){
  select{background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='8'><path d='M1 1l5 5 5-5' fill='none' stroke='%239b9081' stroke-width='1.6' stroke-linecap='round'/></svg>")}
}
/* 勾选框也自己画：原生未勾选是个白方块，暗色下特别扎眼 */
input[type=checkbox]{appearance:none;width:17px;height:17px;padding:0;margin:0;flex:none;
  border:1px solid var(--线强);border-radius:2px;background:transparent;cursor:pointer}
input[type=checkbox]:checked{border-color:var(--点);background-color:var(--点);
  background-repeat:no-repeat;background-position:center;background-size:12px 12px;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='10'><path d='M1 5.4l3.2 3.2L11 1.6' fill='none' stroke='%23f5f1e8' stroke-width='2' stroke-linecap='round'/></svg>")}
@media (prefers-color-scheme:dark){
  input[type=checkbox]:checked{background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='10'><path d='M1 5.4l3.2 3.2L11 1.6' fill='none' stroke='%231a1206' stroke-width='2' stroke-linecap='round'/></svg>")}
}
.when{display:block;font-size:12.5px;color:var(--墨柔);margin:0 0 18px}
.checks{display:flex;flex-wrap:wrap;gap:20px;margin:6px 0 16px}
.checks label{display:flex;align-items:center;gap:8px;margin:0;font-size:13px;color:var(--墨柔)}
.file{margin:0 0 18px}
.file label{font-size:12.5px;color:var(--墨柔);margin:0 0 8px}
.file input[type=file]{width:100%;padding:10px;font-size:13px;background:var(--纸);
  border:1px dashed var(--线强);border-radius:3px;color:var(--墨淡)}
.file .hint{display:block;margin-top:8px}
input[type=file]::file-selector-button{font:400 13px/1 var(--无衬线);margin-right:12px;
  padding:8px 14px;border:1px solid var(--线强);border-radius:2px;background:var(--纸2);
  color:var(--墨);cursor:pointer}

/* ── 按钮：一屏最多一个实心 ── */
button,.btn{display:inline-block;font:400 14.5px/1 var(--无衬线);padding:12px 22px;
  border:1px solid var(--点);border-radius:3px;background:var(--点);color:var(--点上的字);
  cursor:pointer;text-decoration:none}
button:hover,.btn:hover{filter:brightness(1.06);text-decoration:none}
button.plain,.btn.plain{background:transparent;color:var(--墨柔);border-color:var(--线强);
  font-size:13.5px;padding:10px 16px}
button.plain:hover,.btn.plain:hover{color:var(--墨);border-color:var(--墨柔);filter:none}
.actions{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:20px 0 0}
form.inline{display:inline-block;margin:0}

/* ── 说明文字只有两种：提示（灰）和系统通知（左线+底） ── */
.hint{font-size:12.5px;line-height:1.7;color:var(--墨淡);margin:10px 0 0}
.hint.说明{margin:0 0 22px}
.hint.写什么{margin:16px 0 24px;padding-left:14px;border-left:2px solid var(--线);
  font-size:13px;line-height:1.8;color:var(--墨柔)}
.hint.写什么 b{color:var(--墨);font-weight:500}
.meta{font-size:12.5px;line-height:1.7;color:var(--墨淡)}
.facts{font-size:13px;line-height:1.7;color:var(--墨柔);margin:0 0 22px;
  font-variant-numeric:tabular-nums;letter-spacing:.01em}
.notice{margin:0 0 24px;padding:14px 16px;background:var(--纸2);border-left:2px solid var(--点);
  border-radius:0 3px 3px 0;font-size:14.5px;line-height:1.7}
.error{margin:0 0 22px;padding:2px 0 2px 14px;border-left:2px solid var(--坏);color:var(--坏);
  font-size:14.5px;line-height:1.7}
.empty{font-size:14.5px;line-height:1.7;color:var(--墨淡);margin:0 0 22px}

/* ── 卡片：靠底色区分，不描边 ── */
.card{background:var(--纸2);border:0;border-radius:3px;padding:22px 24px;margin:0 0 24px}
.card .meta{margin:8px 0 0}
.card.text h3:first-child,.card.text h4:first-child,.card.text p:first-child{margin-top:0}
.card.text p:last-child,.card.text ul:last-child{margin-bottom:0}
.card.answer{font-size:16.5px;line-height:1.85;border-left:2px solid var(--点);
  border-radius:0 3px 3px 0}
.card.answer p:last-child{margin-bottom:0}

/* ── 一句话：单条页那句当标题读 ── */
.did{font-size:15.5px}
.did.big{font:400 24px/1.5 var(--衬线);margin:14px 0 18px;letter-spacing:.01em}

/* ── 档位：小圆点 + 小字，放在行尾（句子从左边开始读） ── */
.badge{display:inline-flex;align-items:center;gap:6px;flex:none;margin-left:10px;
  font:400 12px/1 var(--无衬线);color:var(--墨淡);white-space:nowrap}
.badge::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--档0);flex:none}
.badge.l0::before{background:var(--档0)}
.badge.l1::before{background:var(--档1)}
.badge.l2::before{background:var(--档2)}
.badge.l3::before{background:var(--档3)}
.badge.plain,.badge.review{border:1px solid var(--线);border-radius:2px;padding:4px 7px;
  font-size:11.5px}
.badge.plain::before,.badge.review::before{display:none}
.badge.review{border-style:dashed}
.badge.priv{color:var(--坏)}
.badge.priv::before{background:var(--坏)}

/* ── 记录流：行距收紧，句子先读，档位在右 ── */
ul.流{list-style:none;padding:0;margin:0}
ul.流 li{border-top:1px solid var(--线淡)}
ul.流 li:first-child{border-top:none}
ul.流 a{display:flex;gap:14px;align-items:baseline;padding:9px 0;color:inherit}
ul.流 a:hover{text-decoration:none}
ul.流 a:hover .did{color:var(--点)}
ul.流 .when{flex:none;min-width:74px;font-size:12px;line-height:1.6;color:var(--墨淡);
  font-variant-numeric:tabular-nums;letter-spacing:.01em}
ul.流 .did{flex:1;font-size:15.5px;line-height:1.55}
ul.流 .did + .badge{margin-left:auto}
.month{display:flex;justify-content:space-between;align-items:baseline;margin:40px 0 2px;
  padding:0 0 10px;border-bottom:1px solid var(--线);
  font:500 13px/1 var(--无衬线);letter-spacing:.02em;color:var(--墨柔)}
.month small{font:400 12px/1 var(--无衬线);color:var(--墨淡)}
.filters{display:flex;flex-wrap:wrap;align-items:baseline;gap:18px;margin:0 0 10px;
  font:400 13px/1 var(--无衬线)}
.filters span{color:var(--墨淡);font-size:12px;letter-spacing:.04em}
.filters a{color:var(--墨柔);padding-bottom:4px;border-bottom:2px solid transparent}
.filters a:hover{color:var(--墨);text-decoration:none}
.filters a.on{color:var(--墨);border-bottom-color:var(--点)}
.more{margin:26px 0;font-size:13px}
.more a{color:var(--墨柔)}

/* ── 目标 / 主题 / 导出列表 ── */
ul.目标们{list-style:none;padding:0;margin:0}
ul.目标们 li{border-top:1px solid var(--线淡)}
ul.目标们 li:first-child{border-top:none}
ul.目标们 a{display:block;padding:16px 0;color:inherit}
ul.目标们 a:hover{text-decoration:none}
ul.目标们 a:hover .title{color:var(--点)}
ul.目标们 .title{font:500 17px/1.45 var(--无衬线)}
ul.目标们 .tag{margin-left:10px;padding:4px 8px;border:1px solid var(--线);border-radius:2px;
  font:400 11.5px/1 var(--无衬线);color:var(--墨淡);vertical-align:2px}
ul.目标们 .meta{display:block;margin:8px 0 0;font-size:12.5px;color:var(--墨淡)}

/* ── 证据卡的档位分布 ── */
ul.档位{list-style:none;padding:0;margin:0 0 32px}
ul.档位 li{display:flex;gap:12px;align-items:baseline;padding:11px 0;
  border-top:1px solid var(--线淡);font-size:15px}
ul.档位 li:first-child{border-top:none}
ul.档位 .badge{margin-left:0;min-width:64px}
ul.档位 b{font:500 15px/1 var(--无衬线);font-variant-numeric:tabular-nums}
ul.档位 .meta{margin:0;flex:1}

/* ── 三线表（设置页） ── */
table.info{width:100%;border-collapse:collapse;font-size:14.5px;margin:0 0 8px}
table.info tr:first-child th,table.info tr:first-child td{border-top:2px solid var(--线强)}
table.info th,table.info td{padding:13px 0;border-bottom:1px solid var(--线淡);
  text-align:left;vertical-align:top}
table.info th{width:32%;padding-right:18px;white-space:nowrap;font-weight:400;color:var(--墨淡);
  font-size:13px}
table.info td{word-break:break-all}

/* ── 零碎 ── */
.anchors{display:flex;flex-wrap:wrap;gap:7px;margin:16px 0 0}
.anchors span{padding:4px 9px;border:1px solid var(--线);border-radius:2px;
  font-size:12px;color:var(--墨淡)}
.blockers{color:var(--坏);font-size:14.5px;margin:14px 0 0}
.why{font-size:16px;line-height:1.8;border-left:2px solid var(--线);padding-left:16px;
  margin:18px 0}
blockquote{margin:18px 0;padding:2px 0 2px 16px;border-left:2px solid var(--点);
  font:400 16px/1.85 var(--衬线)}
blockquote p:last-child{margin-bottom:0}
code{font:400 12.5px/1.5 var(--等宽);background:var(--纸2);padding:2px 6px;border-radius:2px}
em,i{font-style:normal;color:var(--点)}
b,strong{font-weight:500}
footer{margin:76px 0 0;padding:18px 0 0;border-top:1px solid var(--线淡);
  font:400 12px/1.8 var(--无衬线);color:var(--墨淡);letter-spacing:.02em}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}

/* ── 「问老师」 ── */
.问{margin:24px 0 10px;font-size:12.5px;color:var(--墨淡);letter-spacing:.01em}
.快问{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 24px}
.快问 button{font-size:13px;padding:9px 14px}

/* ── 导出物：按段落渲染，看着像一份文件而不是日志 ── */
pre.导出物{white-space:pre-wrap;word-break:break-word;background:var(--纸2);
  border-radius:3px;padding:24px 26px;margin:0;font:16px/1.85 var(--无衬线);color:var(--墨)}
.card.text.导出 h3{font:500 19px/1.5 var(--无衬线);letter-spacing:.01em;color:var(--墨);
  margin:32px 0 10px}
.card.text.导出 h4{font:500 16px/1.6 var(--无衬线);color:var(--墨);margin:24px 0 8px}
.card.text.导出 .大标题{font:500 32px/1.3 var(--衬线);margin:0 0 20px;color:var(--墨)}

/* ── 窄屏 ── */
@media (max-width:560px){
  body{padding:0 18px 60px;font-size:16px}
  header{padding-top:28px;margin-bottom:34px}
  .brand{font-size:24px}
  nav{gap:18px}
  h1{font-size:26px}
  h2{font-size:18px}
  .card{padding:18px 18px}
  ul.流 a{flex-wrap:wrap;gap:4px 12px}
  ul.流 .did{flex-basis:100%;order:2}
  ul.流 .when{order:1}
  ul.流 .badge{order:1;margin-left:auto}
}

/* ── 打印：导出物一页 A4 能直接存 PDF ── */
@media print{
  body{background:#fff;color:#000;max-width:none;padding:0}
  header,footer,.actions,form,.快问,nav{display:none}
  a{color:#000}
  .card,.card.text.导出,pre.导出物{background:#fff;padding:0;border:0}
  h1,h2,h3{break-after:avoid}
}
"""
