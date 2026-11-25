"""server.py —— 本机网页界面的传输层（设计见 docs/WEBUI.md §5）。

这一层只做四件事：

1. 绑定 127.0.0.1，起一个能并发的小服务
2. 路由（哪条 URL 交给哪个处理函数）
3. 三道安全校验（Host / 令牌+Origin / 输出转义）
4. 取数据 → 交给 pages.py 渲染 → 发回去

**页面长什么样全在 pages.py 里**，这个文件不拼 HTML（只有错误页例外，那个太短）。

为什么能并发：`/ask` 要等模型 5~20 秒。单线程的话，等回答的时候整个页面都打不开。
"""

from __future__ import annotations

import secrets
import sys
import traceback
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from life import config, goal, index, jobs, pages, portrait, promote, recorder, retrieve, review, store, tidy
from life import uploads as uploads模块

最大请求体 = 64 * 1024  # 64KB。表单填不出一百个字，再大多半是攻击
每页条数 = 50


# ── 取数据（页面需要的原料）──────────────────────────────────


def _连接():
    return index.连接索引()


def _全部条目() -> list[dict]:
    """所有记录，新的在前。**包含私密记录**——这是你自己的电脑，藏起来反而奇怪。

    私密记录只是不进「提问 / 画像 / 回顾 / 提名」这些会「翻出来」的地方（DESIGN §8）。
    """
    连接 = _连接()
    try:
        行们 = 连接.execute("SELECT id FROM entries ORDER BY ts DESC").fetchall()
        return [e for e in (index.取条目(连接, 行["id"]) for 行 in 行们) if e]
    finally:
        连接.close()


def _写回索引(条目: dict) -> None:
    连接 = _连接()
    try:
        index.写入条目(连接, 条目)
    finally:
        连接.close()


def _统计() -> dict:
    连接 = _连接()
    try:
        数 = index.统计(连接)
    finally:
        连接.close()
    return {
        "条数": 数.get("条目数", 0),
        "待看": 数.get("待看条数", 0),
        "章节": len(store.全部章节()),
        "目标": len(store.全部目标()),
    }


def _最近几天(天数: int = 7) -> list[dict]:
    from datetime import timedelta

    最早 = (store.现在() - timedelta(days=天数 - 1)).date().isoformat()
    return [e for e in _全部条目() if e["ts"][:10] >= 最早]


def _记录视图(查询: dict[str, str]) -> dict:
    全部 = _全部条目()
    部分 = 查询.get("部分", "")
    档位 = 查询.get("档位", "")
    状态 = 查询.get("状态", "")

    筛 = [
        e
        for e in 全部
        if (not 部分 or e["part"] == 部分)
        and (not 档位 or str(e["level"]) == 档位)
        and (not 状态 or e["status"] == 状态)
    ]

    try:
        页 = max(1, int(查询.get("页", "1")))
    except ValueError:
        页 = 1

    起 = (页 - 1) * 每页条数
    片 = 筛[起 : 起 + 每页条数]

    分组: list[tuple[str, list[dict]]] = []
    for 条目 in 片:
        月 = 条目["ts"][:7]
        if not 分组 or 分组[-1][0] != 月:
            分组.append((月, []))
        分组[-1][1].append(条目)

    return {
        "分组": 分组,
        "筛选": {k: v for k, v in {"部分": 部分, "档位": 档位, "状态": 状态}.items() if v},
        "页码": 页,
        "有更早": len(筛) > 起 + 每页条数,
        "总数": len(筛),
    }


def _最新画像() -> tuple[str, str]:
    """（季度名，正文）。没有就返回两个空字符串。"""
    目录 = store.确保vault就绪() / "portrait"
    文件们 = sorted(目录.glob("*.md"))
    if not 文件们:
        return "", ""
    最新 = 文件们[-1]
    return 最新.stem, 最新.read_text(encoding="utf-8")


# ── HTTP 处理 ────────────────────────────────────────────────


class 处理器(BaseHTTPRequestHandler):
    令牌 = ""
    允许的主机: tuple[str, ...] = ()
    允许的来源: frozenset[str] = frozenset()

    # 默认每次请求都打到 stderr，太吵
    def log_message(self, 格式: str, *参数) -> None:  # noqa: A002
        pass

    # ── 安全 ──

    def _主机合法(self) -> bool:
        return (self.headers.get("Host") or "").strip().lower() in self.允许的主机

    def _来源合法(self) -> bool:
        """CSRF 的第二道（第一道是令牌）。

        只拦「明确来自别的站点」的提交：
        - 没有 Origin/Referer（curl、或浏览器隐私设置把它去掉了）→ 放行，靠令牌
        - Origin 是 "null"（沙箱 iframe、某些隐私模式）→ 放行，靠令牌
        - 有明确来源 → 必须正好是本服务的地址

        一开始写成「必须 http://127.0.0.1: 开头」，把正常操作也拦了（真事故），
        所以改成现在这样：**默认放行，只拦说得清的坏来源**。
        """
        来源 = (self.headers.get("Origin") or self.headers.get("Referer") or "").strip()
        if not 来源 or 来源.lower() == "null":
            return True
        return 来源.rstrip("/") in self.允许的来源

    def _来源快照(self) -> str:
        """拦截时把收到的关键头写在页面上，方便排查（这些值不含秘密）。"""
        端口 = self.server.server_address[1]
        return (
            f"Host: {self.headers.get('Host')!r} ｜ "
            f"Origin: {self.headers.get('Origin')!r} ｜ "
            f"Referer: {self.headers.get('Referer')!r} ｜ "
            f"本服务接受的来源: {sorted(self.允许的来源)} ｜ "
            f"实际端口: {端口}"
        )

    def _令牌合法(self, 表单: dict[str, str]) -> bool:
        提交 = (表单.get("token") or "").encode("utf-8")
        真 = self.令牌.encode("utf-8")
        return secrets.compare_digest(提交, 真)

    # ── 输出 ──

    def _页面(self, 状态: int, 内容: str) -> None:
        数据 = 内容.encode("utf-8")
        self.send_response(状态)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(数据)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(数据)

    def _跳(self, 位置: str) -> None:
        """PRG：POST 之后一律 303 跳转，否则刷新会重复提交。

        注意：HTTP 头只能是 latin-1，所以中文 id（目标名、任务名）必须先百分号编码，
        不然一提交就 500。安全字符保持原样，避免二次编码。
        """
        安全位置 = urllib.parse.quote(位置, safe="/?&=:%#")
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", 安全位置)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _出错(self, 状态: int, 标题: str, 说明: str) -> None:
        self._页面(状态, pages.消息(self.令牌, 标题, 说明))

    def _读请求体(self) -> tuple[dict[str, str], list[dict]]:
        """读一次请求体，拆成（普通字段，上传的文件）。

        格式由 Content-Type 决定：纯文字是 urlencoded，带文件是 multipart。
        上限也分两种：文字 64KB，带文件 12MB。
        """
        长度 = int(self.headers.get("Content-Length") or 0)
        if 长度 <= 0:
            return {}, []
        类型 = self.headers.get("Content-Type") or ""
        上限 = (
            uploads模块.最大整体字节 if 类型.startswith("multipart/") else 最大请求体
        )
        if 长度 > 上限:
            raise uploads模块.上传错误(
                f"这次提交太大了（上限 {上限 // (1024 * 1024)}MB）。"
            )
        原始 = self.rfile.read(长度)
        return uploads模块.解析(类型, 原始)

    # ── 分发 ──

    def do_GET(self) -> None:  # noqa: N802
        self._包一层(self._处理GET)

    def do_POST(self) -> None:  # noqa: N802
        self._包一层(self._处理POST)

    def _包一层(self, 处理: Callable[[], None]) -> None:
        """Host 校验 + 兜住任何异常，别把连接甩掉。"""
        if not self._主机合法():
            self._出错(
                HTTPStatus.FORBIDDEN,
                "拒绝了",
                "Host 不对。这个页面只服务 127.0.0.1，别用域名访问。" + chr(10) + self._来源快照(),
            )
            return
        try:
            处理()
        except Exception as 错误:  # noqa: BLE001 —— 兜底就是要抓住所有
            traceback.print_exc(file=sys.stderr)
            self._出错(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "服务器内部出错了",
                f"{type(错误).__name__}: {错误}",
            )

    # ── GET ──

    def _处理GET(self) -> None:
        解析 = urllib.parse.urlparse(self.path)
        路径 = 解析.path
        查询 = {k: v[0] for k, v in urllib.parse.parse_qs(解析.query).items()}

        if 路径 == "/":
            self._今天()
        elif 路径 == "/entries":
            self._页面(HTTPStatus.OK, pages.记录列表(self.令牌, **_记录视图(查询)))
        elif 路径.startswith("/entries/"):
            self._单条(urllib.parse.unquote(路径[len("/entries/") :]))
        elif 路径 == "/ask":
            self._提问(查询)
        elif 路径 == "/goals":
            self._目标列表()
        elif 路径 == "/goals/new":
            self._页面(HTTPStatus.OK, pages.目标表单(self.令牌, None))
        elif 路径.startswith("/goals/"):
            self._目标页(urllib.parse.unquote(路径[len("/goals/") :]))
        elif 路径 == "/chapters":
            章节们 = store.全部章节()
            self._页面(
                HTTPStatus.OK,
                pages.章节列表(self.令牌, 章节们, promote.待确认提名()),
            )
        elif 路径.startswith("/chapters/"):
            self._章节页(urllib.parse.unquote(路径[len("/chapters/") :]))
        elif 路径 == "/portrait":
            self._画像页()
        elif 路径 == "/review":
            self._回顾页()
        elif 路径 == "/review/latest":
            self._回顾文件()
        elif 路径.startswith("/jobs/"):
            self._任务页(urllib.parse.unquote(路径[len("/jobs/") :]))
        elif 路径 == "/settings":
            self._设置页()
        else:
            self._出错(HTTPStatus.NOT_FOUND, "没有这个页面", f"路径：{路径}")

    def _今天(self, 提示: str = "", 状态: int = HTTPStatus.OK, 覆盖数: int | None = None) -> None:
        待 = [e for e in _全部条目() if e["status"] == "needs_review"]
        self._页面(
            状态,
            pages.今天(
                self.令牌,
                待确认数=len(待) if 覆盖数 is None else 覆盖数,
                最近=_最近几天(7)[:12],
                统计=_统计(),
                提示=提示,
                待抽取数=len(store.列出inbox()),
            ),
        )

    def _单条(self, 记录id: str, *, 错误: str = "", 草稿: dict | None = None) -> None:
        try:
            路径 = store.找条目文件(记录id)
        except store.存储错误 as 异常:
            self._出错(HTTPStatus.NOT_FOUND, "找不到这条记录", str(异常))
            return
        if 路径 is None:
            self._出错(HTTPStatus.NOT_FOUND, "找不到这条记录", f"id：{记录id}")
            return
        条目 = store.读条目(路径)
        self._页面(HTTPStatus.OK, pages.单条(self.令牌, 条目, 错误=错误, 草稿=草稿))

    def _提问(self, 查询: dict[str, str]) -> None:
        问题 = (查询.get("q") or "").strip()
        只看召回 = 查询.get("dry") == "1"
        if not 问题:
            self._页面(HTTPStatus.OK, pages.提问(self.令牌, 问题=""))
            return

        try:
            召回, 诊断 = retrieve.召回(问题, 取几条=6)
        except Exception as 错误:  # noqa: BLE001
            self._页面(
                HTTPStatus.OK,
                pages.提问(self.令牌, 问题=问题, 召回=[], 诊断={}, 错误=f"检索失败了：{错误}"),
            )
            return

        if 只看召回:
            self._页面(
                HTTPStatus.OK,
                pages.提问(self.令牌, 问题=问题, 召回=召回, 诊断=诊断, 只看召回=True),
            )
            return

        from life import ask as ask模块

        try:
            结果 = ask模块.问(问题, 取几条=6)
        except Exception as 错误:  # noqa: BLE001
            self._页面(
                HTTPStatus.OK,
                pages.提问(
                    self.令牌, 问题=问题, 召回=召回, 诊断=诊断, 错误=f"这次没回答成：{错误}"
                ),
            )
            return

        回答 = 结果["回答"].strip()
        if 结果["没做到"]:
            回答 += "\n\n（这次有硬要求没做到：" + "；".join(结果["没做到"]) + "）"
        self._页面(
            HTTPStatus.OK,
            pages.提问(self.令牌, 问题=问题, 召回=结果["召回"], 诊断=结果["诊断"], 回答=回答),
        )

    def _目标列表(self) -> None:
        目标们 = goal.全部目标()
        证据们 = {目标["id"]: goal.算证据(目标) for 目标 in 目标们}
        self._页面(HTTPStatus.OK, pages.目标列表(self.令牌, 目标们, 证据们))

    def _目标页(self, 尾巴: str) -> None:
        """`/goals/<id>` 看详情，`/goals/<id>/编辑` 出表单。"""
        编辑 = 尾巴.endswith("/编辑")
        标识 = 尾巴[: -len("/编辑")] if 编辑 else 尾巴
        try:
            目标 = goal.找目标(标识)
        except goal.目标错误 as 错误:
            self._出错(HTTPStatus.NOT_FOUND, "找不到这个目标", str(错误))
            return
        if 编辑:
            self._页面(HTTPStatus.OK, pages.目标表单(self.令牌, 目标))
        else:
            self._页面(HTTPStatus.OK, pages.目标详情(self.令牌, 目标, goal.算证据(目标)))

    def _章节页(self, 标识: str) -> None:
        目标章节 = next(
            (c for c in store.全部章节() if c["id"] == 标识 or c["title"] == 标识), None
        )
        if 目标章节 is None:
            self._出错(HTTPStatus.NOT_FOUND, "找不到这个章节", f"id：{标识}")
            return
        条目们 = [e for e in _全部条目() if e["chapter"] == 目标章节["id"]]
        self._页面(HTTPStatus.OK, pages.章节详情(self.令牌, 目标章节, 条目们))

    def _画像页(self) -> None:
        季度, 正文 = _最新画像()
        self._页面(
            HTTPStatus.OK,
            pages.只读文本页(
                self.令牌,
                标题="画像" + (f"（{季度}）" if 季度 else ""),
                地址="/portrait",
                正文=正文,
                命令="life portrait",
                说明=(
                    "画像写的是假设，不是判决；每条都带「依据：N 次」。"
                    "生成要调模型（一到两分钟），点按钮后台跑，不用等在这里。"
                ),
                按钮=pages.作业按钮(self.令牌, "portrait", "生成 / 重新生成本季度画像"),
            ),
        )

    def _回顾页(self) -> None:
        from life import review

        起, 止, 标签 = review.区间(周=True)
        数据 = review.收集(起, 止)
        摘要 = [
            f"## {标签}",
            "",
            f"- {len(数据['条目们'])} 条记录，投入约 {数据['分钟'] / 60:.0f} 小时",
            "- 证据分布："
            + "、".join(f"{pages.档位名[档]} {数据['分布'].get(档, 0)}" for 档 in (3, 2, 1, 0)),
            "- 和上一段比：" + review._变化文字(数据["分布"], 数据["上一段分布"]),
            "- 晋升事件：" + (f"{len(数据['事件'])} 条" if 数据["事件"] else "没有"),
        ]
        self._页面(
            HTTPStatus.OK,
            pages.只读文本页(
                self.令牌,
                标题="回顾（最近七天）",
                地址="/review",
                正文="\n".join(摘要),
                命令="life review --week",
                说明=(
                    "上面是马上能算出来的数据。"
                    "带叙述的完整回顾要调模型，点按钮后台跑，写完存在 vault/review/。"
                ),
                按钮=pages.作业按钮(self.令牌, "review", "生成带叙述的回顾")
                + (
                    " <a class=\"btn plain\" href=\"/review/latest\">看上次生成的</a>"
                    if (store.确保vault就绪() / "review").glob("*.html")
                    else ""
                ),
            ),
        )

    # ── 后台任务（docs/WEBUI.md §2.6）──

    def _任务页(self, 任务号: str) -> None:
        任务 = jobs.取(任务号)
        if 任务 is None:
            self._出错(HTTPStatus.NOT_FOUND, "找不到这个任务", "进程重启过的话，任务记录就没了。")
            return
        self._页面(HTTPStatus.OK, pages.任务页(self.令牌, 任务))

    def _起作业(self, 动作: str) -> None:
        表 = {
            "portrait": ("生成季度画像", self._作业画像, "/portrait"),
            "review": ("生成带叙述的回顾", self._作业回顾, "/review"),
            "settle": ("归纳最近的记录", self._作业提名, "/chapters"),
            "reindex": ("重建索引", self._作业索引, "/settings"),
            "retry": ("补抽没抽成的记录", self._作业补抽, "/"),
            "tidy": ("瘦身：清理旧缓存与孤儿全文", self._作业瘦身, "/settings"),
        }
        项 = 表.get(动作)
        if 项 is None:
            self._出错(HTTPStatus.NOT_FOUND, "没有这种任务", 动作)
            return
        名称, 函数, 去向 = 项
        任务, _新的 = jobs.启动(动作, 名称, 函数, 去向=去向)
        self._跳(f"/jobs/{任务.id}")

    def _作业画像(self) -> str:
        结果 = portrait.生成()
        尾巴 = ""
        if 结果["缺依据的假设"]:
            尾巴 = f"，其中 {len(结果['缺依据的假设'])} 条假设没写依据（多半是场面话）"
        return f"{结果['季度']} 画像已生成（{结果['token']} token）{尾巴}"

    def _作业回顾(self) -> str:
        文本, 数据 = review.生成(周=True, 用HTML=True)
        目录 = store.确保vault就绪() / "review"
        目录.mkdir(parents=True, exist_ok=True)
        路径 = 目录 / f"{store.现在().date().isoformat()}-周回顾.html"
        路径.write_text(文本, encoding="utf-8")
        return f"写好了 {len(数据['条目们'])} 条记录的回顾：vault/review/{路径.name}"

    def _作业提名(self) -> str:
        结果 = promote.提名()
        if 结果["说明"]:
            return 结果["说明"]
        return f"找到 {结果['主题数']} 个主题，提名 {len(结果['提名'])} 条"

    def _作业补抽(self) -> str:
        结果 = recorder.补抽()
        if 结果["总数"] == 0:
            return "队列是空的，没有要补的。"
        return f"补抽 {结果['成功']} 条，仍失败 {结果['失败']} 条"

    def _作业瘦身(self) -> str:
        结果 = tidy.执行()
        return (
            f"清掉 {结果['缓存']} 个缓存、{结果['孤儿媒体']} 个孤儿全文，"
            f"共 {tidy.人话(结果['字节'])}。记录一条都没动。"
        )

    def _作业索引(self) -> str:
        结果 = index.重建索引()
        return f"扫描 {结果['扫描']} 个文件，写入 {结果['成功']} 条记录"

    def _回顾文件(self) -> None:
        """把最近生成的那份回顾 HTML 直接发给浏览器。"""
        目录 = store.确保vault就绪() / "review"
        文件们 = sorted(目录.glob("*.html"))
        if not 文件们:
            self._出错(HTTPStatus.NOT_FOUND, "还没生成过回顾", "回回顾页点一下「生成」。")
            return
        数据 = 文件们[-1].read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(数据)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(数据)

    def _设置页(self) -> None:
        from life import llm

        模型名 = "（没配 providers.yaml）"
        try:
            抽取 = config.读取任务("extract")
            模型名 = 抽取.model if 抽取 else 模型名
        except config.配置错误 as 错误:
            模型名 = f"配置有错：{错误}"

        能, 原因 = llm.能向量()
        连接 = _连接()
        try:
            数 = index.统计(连接)
        finally:
            连接.close()

        占用 = tidy.扫描()

        self._页面(
            HTTPStatus.OK,
            pages.设置(
                self.令牌,
                {
                    "项": [
                        ("数据目录", str(config.vault目录())),
                        ("工作区", str(config.工作区根目录())),
                        ("抽取模型", str(模型名)),
                        ("向量检索", "可以用" if 能 else f"不可用（{原因}）"),
                        ("记录条数", str(数.get("条目数", 0))),
                        ("待确认", str(数.get("待看条数", 0))),
                        ("累计 token", str(数.get("总token", 0))),
                        ("监听地址", f"127.0.0.1:{self.server.server_address[1]}"),
                        ("Python", sys.version.split()[0]),
                        (
                            "抽取缓存",
                            f"{占用['缓存总数']} 个（{tidy.人话(占用['缓存字节'])}）"
                            f"｜可清 {占用['缓存可清']} 个",
                        ),
                        (
                            "媒体全文",
                            f"{占用['媒体总数']} 个｜孤儿 {占用['孤儿媒体']} 个"
                            f"（{tidy.人话(占用['孤儿字节'])}）",
                        ),
                    ]
                },
                按钮=pages.作业按钮(self.令牌, "tidy", "瘦身（清 90 天前的缓存）")
                + pages.作业按钮(self.令牌, "reindex", "重建索引", 次要=True),
            ),
        )

    # ── POST ──

    def _处理POST(self) -> None:
        if not self._来源合法():
            self._出错(
                HTTPStatus.FORBIDDEN,
                "拒绝了",
                "这个表单不是从本页面提交的。如果你是在本页面点的按钮，那就是我判断错了，请把下面这一行发给我：" + chr(10) + self._来源快照(),
            )
            return

        try:
            表单, 文件们 = self._读请求体()
        except uploads模块.上传错误 as 错误:
            self._今天(str(错误), 状态=HTTPStatus.BAD_REQUEST)
            return

        if not self._令牌合法(表单):
            self._出错(HTTPStatus.FORBIDDEN, "拒绝了", "令牌不对（页面开了太久？刷新一下再试）。")
            return

        路径 = urllib.parse.urlparse(self.path).path

        if 路径 == "/add":
            self._记一条(表单, 文件们)
        elif 路径.startswith("/entries/") and 路径.endswith("/settle"):
            self._确认(urllib.parse.unquote(路径[len("/entries/") : -len("/settle")]))
        elif 路径.startswith("/entries/"):
            self._改条目(urllib.parse.unquote(路径[len("/entries/") :]), 表单)
        elif 路径 == "/goals/new":
            self._建目标(表单)
        elif 路径.startswith("/jobs/"):
            self._起作业(urllib.parse.unquote(路径[len("/jobs/") :]))
        elif 路径.startswith("/promotions/"):
            self._晋升(urllib.parse.unquote(路径[len("/promotions/") :]))
        elif 路径.startswith("/goals/"):
            self._改目标(urllib.parse.unquote(路径[len("/goals/") :]), 表单)
        else:
            self._出错(HTTPStatus.NOT_FOUND, "没有这个页面", f"路径：{路径}")

    def _记一条(self, 表单: dict[str, str], 文件们: list[dict] | None = None) -> None:
        原文 = (表单.get("text") or "").strip()
        文件们 = 文件们 or []
        保留原文件 = 表单.get("keep") == "1"

        if not 原文 and not 文件们:
            self._今天("什么都没写，也没选文件。再试一次？", 状态=HTTPStatus.BAD_REQUEST)
            return

        try:
            某天, 时间说明 = recorder.解析过去时间(表单.get("when", ""))
        except ValueError as 错误:
            self._今天(str(错误), 状态=HTTPStatus.BAD_REQUEST)
            return
        时间备注 = ""
        if 表单.get("when", "").strip():
            时间备注 = "\n" + 时间说明

        临时: Path | None = None
        try:
            if 文件们:
                文件 = 文件们[0]
                try:
                    类型, 后缀 = uploads模块.判定(文件["文件名"], 文件["数据"])
                except uploads模块.上传错误 as 错误:
                    self._今天(str(错误), 状态=HTTPStatus.BAD_REQUEST)
                    return

                临时 = self._存上传(文件["数据"], 后缀)

                结果 = recorder.记录一条(
                    原文,
                    图片=临时 if 类型 == "image" else None,
                    文档=临时 if 类型 == "document" else None,
                    文档原名=文件["文件名"],
                    保留原文件=保留原文件,
                    时间=表单.get("when", ""),
                    情感=表单.get("emotion") == "1",
                    私密=表单.get("private") == "1",
                    提示=lambda _: None,
                )
            else:
                结果 = recorder.记录一条(
                    原文,
                    时间=表单.get("when", ""),
                    情感=表单.get("emotion") == "1",
                    私密=表单.get("private") == "1",
                    提示=lambda _: None,
                )
        finally:
            # 服务器自己写的这份临时副本用完就删；recorder 已经另外存了一份
            if 临时 is not None:
                临时.unlink(missing_ok=True)

        if 结果["状态"] == "输入有问题":
            self._今天(结果["错误"], 状态=HTTPStatus.BAD_REQUEST)
        elif 结果["状态"] == "配置错误":
            self._今天("已存好，但模型没配好，没法压缩。配好之后跑 life retry。")
        elif 结果["状态"] == "抽取失败":
            self._今天(
                f"已存好，但抽取没成功（{结果['错误'][:80]}）。联网后跑 life retry 就能补上。"
            )
        elif 结果["状态"] == "重复":
            self._今天("这条之前记过了，没重复存。")
        else:
            if 时间备注:
                self._今天(时间备注.strip(), 状态=HTTPStatus.OK)
            else:
                self._跳("/")

    def _存上传(self, 数据: bytes, 后缀: str) -> Path:
        """把上传的东西写进 vault 的暂存目录。文件名一律自己取，不用用户给的名字。"""
        目录 = store.确保vault就绪() / "inbox" / "文件暂存"
        目录.mkdir(parents=True, exist_ok=True)
        路径 = 目录 / f"上传-{secrets.token_hex(6)}{后缀}"
        路径.write_bytes(数据)
        return 路径

    def _改条目(self, 记录id: str, 表单: dict[str, str]) -> None:
        try:
            level = int(表单.get("level", "0"))
        except ValueError:
            level = -1

        try:
            条目 = store.改条目字段(
                记录id,
                did=表单.get("did"),
                level=level,
                outcome=表单.get("outcome") or None,
                status=表单.get("status") or None,
                when=表单.get("when"),
            )
        except store.存储错误 as 错误:
            self._单条(
                记录id,
                错误=str(错误),
                草稿={
                    "did": 表单.get("did", ""),
                    "level": level,
                    "outcome": 表单.get("outcome", ""),
                    "status": 表单.get("status", ""),
                    "when": 表单.get("when", ""),
                },
            )
            return

        _写回索引(条目)
        self._跳(f"/entries/{urllib.parse.quote(记录id)}")

    def _确认(self, 记录id: str) -> None:
        try:
            条目 = store.改条目状态(记录id, "settled")
        except store.存储错误 as 错误:
            self._出错(HTTPStatus.NOT_FOUND, "确认失败", str(错误))
            return
        _写回索引(条目)
        self._跳("/")

    def _建目标(self, 表单: dict[str, str]) -> None:
        草稿 = {
            "title": (表单.get("title") or "").strip(),
            "horizon": 表单.get("horizon") or "term",
            "why": 表单.get("why") or "",
            "due": 表单.get("due") or "",
            "status": 表单.get("status") or "active",
        }
        if not 草稿["title"]:
            self._页面(
                HTTPStatus.BAD_REQUEST,
                pages.目标表单(self.令牌, None, 错误="标题不能空着。", 草稿=草稿),
            )
            return
        try:
            goal.建目标(
                草稿["title"], 期限=草稿["horizon"], 为什么=草稿["why"], 截止=草稿["due"]
            )
        except (goal.目标错误, store.存储错误) as 错误:
            self._页面(
                HTTPStatus.BAD_REQUEST,
                pages.目标表单(self.令牌, None, 错误=str(错误), 草稿=草稿),
            )
            return
        self._跳("/goals")

    def _改目标(self, 标识: str, 表单: dict[str, str]) -> None:
        try:
            目标 = goal.找目标(标识)
            目标 = goal.更新目标(
                标识,
                标题=表单.get("title"),
                期限=表单.get("horizon") or None,
                为什么=表单.get("why"),
                截止=表单.get("due"),
                状态=表单.get("status") or None,
            )
        except (goal.目标错误, store.存储错误) as 错误:
            self._出错(HTTPStatus.BAD_REQUEST, "改不了", str(错误))
            return
        self._跳(f"/goals/{urllib.parse.quote(目标['id'])}")

    def _晋升(self, 尾巴: str) -> None:
        要 = 尾巴.endswith("/yes")
        标题 = 尾巴[: -len("/yes")] if 要 else 尾巴[: -len("/no")]
        try:
            if 要:
                promote.确认(标题)
            else:
                promote.拒绝(标题)
        except promote.晋升错误 as 错误:
            self._出错(HTTPStatus.BAD_REQUEST, "处理不了", str(错误))
            return
        self._跳("/chapters")


# ── 启动 ─────────────────────────────────────────────────────


def 造服务器(端口: int = 8770) -> ThreadingHTTPServer:
    """只绑 127.0.0.1。端口传 0 = 让系统随便给一个（测试用）。"""
    服务器 = ThreadingHTTPServer(("127.0.0.1", int(端口)), 处理器)
    服务器.daemon_threads = True
    实际端口 = 服务器.server_address[1]
    处理器.令牌 = secrets.token_urlsafe(24)
    处理器.允许的主机 = (f"127.0.0.1:{实际端口}", f"localhost:{实际端口}")
    # 只接受这一份来源。Origin 精确匹配，不做前缀判断（前缀会把 127.0.0.1:其它端口 也放进来）。
    处理器.允许的来源 = frozenset(
        {f"http://127.0.0.1:{实际端口}", f"http://localhost:{实际端口}"}
    )
    return 服务器


def 启动(端口: int = 8770, *, 打开浏览器: bool = False) -> None:
    import webbrowser

    服务器 = 造服务器(端口)
    地址 = f"http://127.0.0.1:{服务器.server_address[1]}/"
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
