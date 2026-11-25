"""server.py —— 本机网页界面（DESIGN.md §10 第 5 周）。

**只做两件事**，别的一律不做：

1. 新建 / 修改目标
2. 把 `needs_review` 的记录确认成 `settled`

不做的：批量编辑、富文本、拖拽排序、上传图片、账号、多用户。

三条安全底线（本地工具也不能省）：

- 只绑 `127.0.0.1`——局域网里别的机器连不上
- 校验 `Host` 头——防止 DNS rebinding（别人做一个域名解析到 127.0.0.1 来打你）
- 每个表单带一次性令牌 + 校验 `Origin`——防止你在别的网页上被诱导提交

技术选择：标准库 `http.server` + 原生表单提交。不引前端框架、不用 JS 框架、
不起 JS 构建。原因见 docs/features/网页编辑.md。
"""

from __future__ import annotations

import html
import secrets
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from life import goal, index, store

最大请求体 = 64 * 1024  # 64KB，够填表单了；再大多半是攻击


class 网页错误(Exception):
    """网页界面内部的问题。"""


# ── 页面 ─────────────────────────────────────────────────────


def _布局(标题: str, 正文: str, 令牌: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="{令牌}">
<title>{html.escape(标题)} · 你过得怎么样</title>
<style>{_样式()}</style>
</head>
<body>
<header>
  <h1><a href="/">你过得怎么样</a></h1>
  <p class="sub">本机界面 · 只在 127.0.0.1 上，别人连不进来</p>
</header>
{正文}
<footer>这个页面能改东西：改的是 <code>vault/</code> 里的 markdown 文件本身。改完即生效，没有「保存到云」这一步。</footer>
</body>
</html>
"""


def _首页(令牌: str) -> str:
    待确认 = [e for e in _全部条目() if e["status"] == "needs_review"]
    目标们 = goal.全部目标()

    块: list[str] = []

    块.append('<section><h2>待确认的记录 <small>（抽取时没把握的那些）</small></h2>')
    if 待确认:
        for 条目 in 待确认:
            块.append(
                f"""<article class="card">
  <div class="when">{html.escape(条目['ts'][:16].replace('T', ' '))}</div>
  <p class="did">{html.escape(条目['did'])}</p>
  <form method="post" action="/entry/{urllib.parse.quote(条目['id'])}/settle">
    <input type="hidden" name="token" value="{令牌}">
    <button type="submit">就是这样，确认</button>
  </form>
</article>"""
            )
    else:
        块.append('<p class="empty">没有待确认的记录。</p>')
    块.append("</section>")

    块.append('<section><h2>目标 <small>（不做百分比，不标红）</small></h2>')
    if 目标们:
        块.append('<ul class="goals">')
        for 目标 in 目标们:
            状态 = {
                "active": "进行中",
                "done": "已完成",
                "stopped": "已停",
                "paused": "暂停",
            }.get(目标["status"], 目标["status"])
            块.append(
                f'<li><a href="/goal/{urllib.parse.quote(目标["id"])}">{html.escape(目标["title"])}</a>'
                f'<span class="tag">{html.escape(状态)}</span></li>'
            )
        块.append("</ul>")
    else:
        块.append('<p class="empty">还没有目标。</p>')
    块.append('<p><a class="btn" href="/goal/new">＋ 新建目标</a></p>')
    块.append("</section>")

    return _布局("首页", "\n".join(块), 令牌)


def _目标表单(令牌: str, 目标: dict | None, 错误: str = "") -> str:
    """新建和编辑共用一张表单。目标为 None 就是新建。"""
    新 = 目标 is None
    标题 = "" if 新 else 目标["title"]
    为什么 = "" if 新 else 目标["why"]
    截止 = "" if 新 else 目标["due"]
    期限 = "term" if 新 else 目标["horizon"]
    状态 = "active" if 新 else 目标["status"]

    def 选项(值们: dict[str, str], 当前: str) -> str:
        return "".join(
            f'<option value="{k}"{" selected" if k == 当前 else ""}>{html.escape(v)}</option>'
            for k, v in 值们.items()
        )

    动作 = "/goal/new" if 新 else f"/goal/{urllib.parse.quote(目标['id'])}"
    错误块 = f'<p class="error">{html.escape(错误)}</p>' if 错误 else ""

    正文 = f"""
<section>
  <h2>{'新建目标' if 新 else '修改目标'}</h2>
  {错误块}
  <form method="post" action="{动作}" class="form">
    <input type="hidden" name="token" value="{令牌}">
    <label>标题 <input name="title" value="{html.escape(标题)}" required maxlength="60"></label>
    <label>期限
      <select name="horizon">{选项({"short": "短期（2周~1月）", "term": "一学期~半年", "long": "长期（1~3年）"}, 期限)}</select>
    </label>
    <label>为什么想要它
      <textarea name="why" rows="3" maxlength="300">{html.escape(为什么)}</textarea>
    </label>
    <label>截止日期 <input name="due" value="{html.escape(截止)}" placeholder="2027-01-15"></label>
    <label>状态
      <select name="status">{选项({"active": "进行中", "done": "已完成", "stopped": "已停", "paused": "暂停"}, 状态)}</select>
    </label>
    <p><button type="submit">{'立这个目标' if 新 else '保存修改'}</button>
       <a class="btn plain" href="/">算了，回去</a></p>
  </form>
  <p class="hint">没有「完成度」这一栏——进度不是线性的，百分比是骗人的。看证据请用命令行 <code>life goal show</code>。</p>
</section>
"""
    return _布局("新建目标" if 新 else "修改目标", 正文, 令牌)


def _消息页(令牌: str, 标题: str, 说明: str) -> str:
    正文 = f'<section><h2>{html.escape(标题)}</h2><p>{html.escape(说明)}</p><p><a class="btn" href="/">回首页</a></p></section>'
    return _布局(标题, 正文, 令牌)


# ── 数据 ─────────────────────────────────────────────────────


def _全部条目() -> list[dict]:
    连接 = index.连接索引()
    try:
        行们 = 连接.execute("SELECT id FROM entries WHERE private = 0 ORDER BY ts DESC").fetchall()
        return [e for e in (index.取条目(连接, 行["id"]) for 行 in 行们) if e]
    finally:
        连接.close()


def _写回索引(条目: dict) -> None:
    连接 = index.连接索引()
    try:
        index.写入条目(连接, 条目)
    finally:
        连接.close()


# ── HTTP ─────────────────────────────────────────────────────


class 处理器(BaseHTTPRequestHandler):
    # 由 启动() 填进去
    令牌 = ""
    端口 = 8770
    允许的主机: tuple[str, ...] = ()

    # 默认会把每次请求打到 stderr，太吵；只留错误
    def log_message(self, 格式: str, *参数) -> None:  # noqa: A002
        pass

    # ── 公共 ──

    def _主机合法(self) -> bool:
        """防 DNS rebinding：只认 127.0.0.1 / localhost 带本端口。"""
        主机 = (self.headers.get("Host") or "").strip().lower()
        return 主机 in self.允许的主机

    def _来源合法(self) -> bool:
        """POST 的 Origin/Referer 必须是自己。浏览器提交表单会带，别的站点带不了。"""
        来源 = (self.headers.get("Origin") or self.headers.get("Referer") or "").strip()
        if not 来源:
            return True  # 命令行 curl 之类不带，交给令牌兜底
        for 前缀 in ("http://127.0.0.1:", "http://localhost:"):
            if 来源.startswith(前缀):
                return True
        return False

    def _发送(self, 状态: int, 内容: str, 类型: str = "text/html; charset=utf-8") -> None:
        数据 = 内容.encode("utf-8")
        self.send_response(状态)
        self.send_header("Content-Type", 类型)
        self.send_header("Content-Length", str(len(数据)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(数据)

    def _跳回(self, 位置: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", 位置)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _拒绝(self, 说明: str) -> None:
        self._发送(HTTPStatus.FORBIDDEN, _消息页(self.令牌, "拒绝了", 说明))

    def _读表单(self) -> dict[str, str]:
        长度 = int(self.headers.get("Content-Length") or 0)
        if 长度 <= 0 or 长度 > 最大请求体:
            return {}
        原始 = self.rfile.read(长度).decode("utf-8", errors="replace")
        解析 = urllib.parse.parse_qs(原始, keep_blank_values=True)
        return {键: 值[0] for 键, 值 in 解析.items()}

    # ── GET ──

    def do_GET(self) -> None:  # noqa: N802
        if not self._主机合法():
            self._拒绝("Host 不对。这个页面只服务 127.0.0.1，别用域名访问。")
            return

        路径 = urllib.parse.urlparse(self.path).path

        if 路径 == "/":
            self._发送(HTTPStatus.OK, _首页(self.令牌))
            return

        if 路径 == "/goal/new":
            self._发送(HTTPStatus.OK, _目标表单(self.令牌, None))
            return

        if 路径.startswith("/goal/"):
            标识 = urllib.parse.unquote(路径[len("/goal/") :])
            try:
                目标 = goal.找目标(标识)
            except goal.目标错误 as 错误:
                self._发送(HTTPStatus.NOT_FOUND, _消息页(self.令牌, "找不到这个目标", str(错误)))
                return
            self._发送(HTTPStatus.OK, _目标表单(self.令牌, 目标))
            return

        self._发送(HTTPStatus.NOT_FOUND, _消息页(self.令牌, "没有这个页面", 路径))

    # ── POST ──

    def do_POST(self) -> None:  # noqa: N802
        if not self._主机合法():
            self._拒绝("Host 不对。")
            return
        if not self._来源合法():
            self._拒绝("这个表单不是从本页面提交的。")
            return

        表单 = self._读表单()
        提交的令牌 = (表单.get("token") or "").encode("utf-8")
        真令牌 = self.令牌.encode("utf-8")
        if not secrets.compare_digest(提交的令牌, 真令牌):
            self._拒绝("令牌不对（可能是页面开了太久，刷新一下再试）。")
            return

        路径 = urllib.parse.urlparse(self.path).path

        if 路径 == "/goal/new":
            self._建目标(表单)
            return

        if 路径.startswith("/goal/"):
            self._改目标(urllib.parse.unquote(路径[len("/goal/") :]), 表单)
            return

        if 路径.startswith("/entry/") and 路径.endswith("/settle"):
            记录id = urllib.parse.unquote(路径[len("/entry/") : -len("/settle")])
            self._确认记录(记录id)
            return

        self._发送(HTTPStatus.NOT_FOUND, _消息页(self.令牌, "没有这个页面", 路径))

    # ── 三个动作 ──

    def _建目标(self, 表单: dict[str, str]) -> None:
        标题 = (表单.get("title") or "").strip()
        if not 标题:
            self._发送(HTTPStatus.BAD_REQUEST, _目标表单(self.令牌, None, "标题不能空着。"))
            return
        try:
            goal.建目标(
                标题,
                期限=表单.get("horizon") or "term",
                为什么=表单.get("why") or "",
                截止=表单.get("due") or "",
            )
        except (goal.目标错误, store.存储错误) as 错误:
            self._发送(HTTPStatus.BAD_REQUEST, _目标表单(self.令牌, None, str(错误)))
            return
        self._跳回("/")

    def _改目标(self, 标识: str, 表单: dict[str, str]) -> None:
        try:
            目标 = goal.找目标(标识)
            goal.更新目标(
                标识,
                标题=表单.get("title"),
                期限=表单.get("horizon") or None,
                为什么=表单.get("why"),
                截止=表单.get("due"),
                状态=表单.get("status") or None,
            )
        except goal.目标错误 as 错误:
            self._发送(HTTPStatus.BAD_REQUEST, _消息页(self.令牌, "改不了", str(错误)))
            return
        self._跳回(f"/goal/{urllib.parse.quote(目标['id'])}")

    def _确认记录(self, 记录id: str) -> None:
        try:
            条目 = store.改条目状态(记录id, "settled")
        except store.存储错误 as 错误:
            self._发送(HTTPStatus.NOT_FOUND, _消息页(self.令牌, "找不到这条记录", str(错误)))
            return
        _写回索引(条目)
        self._跳回("/")


# ── 启动 ─────────────────────────────────────────────────────


def 造服务器(端口: int = 8770) -> HTTPServer:
    """造一个只绑 127.0.0.1 的服务器（不阻塞）。测试里用得到。

    端口传 0 表示「随便给我一个空的」，这时允许的主机要按真实端口算。
    """
    服务器 = HTTPServer(("127.0.0.1", int(端口)), 处理器)
    实际端口 = 服务器.server_address[1]
    处理器.令牌 = secrets.token_urlsafe(24)
    处理器.允许的主机 = (f"127.0.0.1:{实际端口}", f"localhost:{实际端口}")
    return 服务器


def 启动(端口: int = 8770, *, 打开浏览器: bool = False) -> None:
    """一直跑到你按 Ctrl+C。"""
    import webbrowser

    服务器 = 造服务器(端口)
    真实端口 = 服务器.server_address[1]
    地址 = f"http://127.0.0.1:{真实端口}/"
    print(f"· 网页界面已启动：{地址}")
    print("· 只绑在本机 127.0.0.1，局域网里的其它机器连不上。")
    print("· 按 Ctrl+C 停止。")
    if 打开浏览器:
        webbrowser.open(地址)
    try:
        服务器.serve_forever()
    except KeyboardInterrupt:
        print("\n· 停了。")
    finally:
        服务器.server_close()


def _样式() -> str:
    return """
:root{--纸:#faf8f4;--墨:#22201d;--淡:#7b746c;--线:#e2ddd4;--卡:#fffdf9;--点:#7d9b76;--坏:#b5544a}
@media (prefers-color-scheme:dark){:root{--纸:#1b1a18;--墨:#e8e3da;--淡:#9a938a;--线:#332f2b;--卡:#232120;--点:#8fae86;--坏:#d0857b}}
*{box-sizing:border-box}
body{max-width:720px;margin:0 auto;padding:28px 18px 60px;background:var(--纸);color:var(--墨);
  font:15px/1.7 "Microsoft YaHei","PingFang SC",system-ui,sans-serif}
header h1{font-size:20px;margin:0 0 4px}
header h1 a{color:inherit;text-decoration:none}
.sub{color:var(--淡);font-size:12px;margin:0 0 22px}
h2{font-size:14px;color:var(--淡);letter-spacing:.06em;margin:26px 0 10px}
h2 small{font-weight:400;letter-spacing:0}
.card{background:var(--卡);border:1px solid var(--线);border-left:3px solid var(--点);
  border-radius:8px;padding:12px 14px;margin:0 0 10px}
.when{font-size:12px;color:var(--淡)}
.did{margin:6px 0 10px;font-size:15px}
button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid var(--点);
  background:var(--点);color:#fff;cursor:pointer}
button:hover{filter:brightness(1.06)}
.btn{display:inline-block;padding:6px 14px;border-radius:6px;border:1px solid var(--点);
  background:var(--点);color:#fff;text-decoration:none;font-size:14px}
.btn.plain{background:transparent;color:var(--淡);border-color:var(--线)}
.goals{list-style:none;padding:0;margin:0}
.goals li{padding:8px 0;border-bottom:1px solid var(--线)}
.goals a{color:inherit}
.tag{float:right;font-size:12px;color:var(--淡);border:1px solid var(--线);border-radius:999px;padding:0 8px}
.form label{display:block;margin:0 0 14px;font-size:13px;color:var(--淡)}
.form input,.form textarea,.form select{display:block;width:100%;margin-top:5px;padding:8px;
  font:inherit;color:var(--墨);background:var(--卡);border:1px solid var(--线);border-radius:6px}
.form textarea{resize:vertical}
.error{color:var(--坏);font-size:13px}
.hint{color:var(--淡);font-size:12px;margin-top:18px}
.empty{color:var(--淡);font-size:13px}
code{background:var(--线);padding:1px 5px;border-radius:4px;font-size:12px}
footer{margin-top:40px;padding-top:12px;border-top:1px solid var(--线);color:var(--淡);font-size:12px}
"""
