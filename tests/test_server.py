"""测网页界面（docs/WEBUI.md §7 的验收清单）。

全部是真起服务器、真发 HTTP 请求、真看磁盘上的文件变没变。
不测内部函数「返回了什么」——只测用户点一下能看到什么、文件里留下什么。
"""

from __future__ import annotations

import http.client
import re
import threading
import urllib.parse
from datetime import timedelta

import pytest

from life import index, llm, server as server模块, store


@pytest.fixture()
def 站(临时工作区):
    服务器 = server模块.造服务器(0)
    端口 = 服务器.server_address[1]
    线程 = threading.Thread(target=服务器.serve_forever, daemon=True)
    线程.start()
    try:
        yield 端口
    finally:
        服务器.shutdown()
        服务器.server_close()


@pytest.fixture()
def 假抽取(monkeypatch):
    """让抽取稳定成功：把用户写的那句话原样当成 did 返回。"""

    def 调用(任务名, 系统提示, 用户内容, **kw):
        import json

        原文 = " ".join(用户内容.split("\n\n")[0].split())[:60]
        return llm.模型回复(
            文本=json.dumps(
                {
                    "entries": [
                        {
                            "did": 原文,
                            "body": 原文,
                            "part": "record",
                            "minutes": 0,
                            "outcome": "done",
                            "anchors": {"tech": ["OAuth"], "people": [], "link": ""},
                            "emotion": {"valence": 0, "arousal": 0.3, "trigger": "", "quote": ""},
                            "level": 2,
                            "goal": "",
                            "blockers": [],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            输入token=1,
            输出token=1,
            模型名="测试",
            降级到第几级=1,
        )

    monkeypatch.setattr(llm, "调用", 调用)


# ── 小工具 ───────────────────────────────────────────────────


def 请求(端口, 方法, 路径, *, 表单=None, 主机=None, 来源=None, 原始=None, 类型=None):
    连接 = http.client.HTTPConnection("127.0.0.1", 端口, timeout=30)
    头, 体 = {}, None
    if 原始 is not None:
        体 = 原始
        头["Content-Type"] = 类型 or "application/octet-stream"
    elif 表单 is not None:
        体 = urllib.parse.urlencode(表单)
        头["Content-Type"] = "application/x-www-form-urlencoded"
    if 主机 is not None:
        头["Host"] = 主机
    if 来源 is not None:
        头["Origin"] = 来源
    连接.request(方法, 路径, body=体, headers=头)
    响应 = 连接.getresponse()
    内容 = 响应.read().decode("utf-8", errors="replace")
    位置 = 响应.getheader("Location")
    连接.close()
    return 响应.status, 内容, 位置


def 查询(路径: str, **参数) -> str:
    return 路径 + ("?" + urllib.parse.urlencode(参数) if 参数 else "")


def 令牌(端口):
    _, 页面, _ = 请求(端口, "GET", "/")
    匹配 = re.search(r'name="csrf-token" content="([^"]+)"', 页面)
    assert 匹配, "页面里没有 csrf-token"
    return 匹配.group(1)


def 造记录(标题, *, 天前=0, 档=2, 部分="record", 私密=False, 状态="settled", 目标="", 章节=""):
    时间 = (store.现在() - timedelta(days=天前)).replace(microsecond=0)
    编号, 时间 = store.分配id(时间)
    条目 = store.新建条目(
        id=编号, ts=store.时间文本(时间), did=标题, body=标题,
        level=档, part=部分, private=私密, status=状态, goal=目标, chapter=章节,
        anchors={"tech": ["OAuth"], "people": [], "link": ""},
    )
    store.写条目(条目)
    连接 = index.连接索引()
    try:
        index.写入条目(连接, 条目)
    finally:
        连接.close()
    return 编号


# ── M0：今天 / 记一条 / 待确认 / 目标 ─────────────────────────


def test_首页有记一条的入口(临时工作区, 站):
    状态, 页面, _ = 请求(站, "GET", "/")
    assert 状态 == 200
    assert "记一条" in 页面
    assert 'action="/add"' in 页面
    assert "最近七天" in 页面
    for 名 in ("今天", "记录", "提问", "目标", "章节", "画像", "回顾", "设置"):
        assert f">{名}</a>" in 页面


def test_在页面上记一条(临时工作区, 站, 假抽取):
    _, 首页, _ = 请求(站, "GET", "/")
    assert "还没有记录" in 首页

    状态, _, _ = 请求(
        站, "POST", "/add",
        表单={"token": 令牌(站), "text": "今天把 OAuth 调通了，卡在 state 参数签名"},
    )
    assert 状态 in (200, 303)

    文件们 = list((临时工作区 / "vault" / "now").rglob("*.md"))
    assert len(文件们) == 1
    assert "OAuth" in store.读条目(文件们[0])["did"]

    _, 首页2, _ = 请求(站, "GET", "/")
    assert "OAuth" in 首页2


def test_勾了感受就是情感记录(临时工作区, 站, 假抽取):
    请求(
        站, "POST", "/add",
        表单={"token": 令牌(站), "text": "今天很累，什么都不想做", "emotion": "1"},
    )
    条目 = store.读条目(next((临时工作区 / "vault" / "now").rglob("*.md")))
    assert 条目["part"] == "emotion"


def test_勾了只存本地就不发给模型(临时工作区, 站, monkeypatch):
    def 不许调用(*a, **k):
        raise AssertionError("私密记录不该调用模型")

    monkeypatch.setattr(llm, "调用", 不许调用)

    状态, 页面, _ = 请求(
        站, "POST", "/add", 表单={"token": 令牌(站), "text": "这句只存本地", "private": "1"}
    )
    assert 状态 in (200, 303), 页面

    条目 = store.读条目(next((临时工作区 / "vault" / "now").rglob("*.md")))
    assert 条目["private"] is True


def test_断网时页面上记一条也成功(临时工作区, 站, monkeypatch):
    def 断网(*a, **k):
        raise llm.网络错误("模拟断网")

    monkeypatch.setattr(llm, "调用", 断网)

    状态, 页面, _ = 请求(
        站, "POST", "/add", 表单={"token": 令牌(站), "text": "今天在图书馆坐了一下午"}
    )
    assert 状态 == 200
    assert "已存好" in 页面
    assert "life retry" in 页面

    待抽 = list((临时工作区 / "vault" / "inbox").glob("*.json"))
    assert len(待抽) == 1


def test_待确认列表和确认按钮(临时工作区, 站):
    编号 = 造记录("很累，什么都不想做", 部分="emotion", 状态="needs_review")

    状态, 页面, _ = 请求(站, "GET", "/")
    assert 状态 == 200
    assert "等你确认" in 页面

    _, 列表, _ = 请求(站, "GET", 查询("/entries", 状态="needs_review"))
    assert "很累" in 列表

    请求(站, "POST", f"/entries/{编号}/settle", 表单={"token": 令牌(站)})
    assert store.读条目(store.找条目文件(编号))["status"] == "settled"


def test_在页面上新建和修改目标(临时工作区, 站):
    状态, _, _ = 请求(
        站, "POST", "/goals/new",
        表单={"token": 令牌(站), "title": "学完后端基础", "horizon": "term", "why": "想自己做网站"},
    )
    assert 状态 in (200, 303)

    文件 = 临时工作区 / "vault" / "goals" / "学完后端基础.md"
    assert 文件.exists()
    assert "想自己做网站" in 文件.read_text(encoding="utf-8")

    请求(
        站, "POST", "/goals/" + urllib.parse.quote("学完后端基础"),
        表单={"token": 令牌(站), "title": "学完后端", "horizon": "long",
              "why": "", "due": "2027-06-01", "status": "paused"},
    )
    正文 = 文件.read_text(encoding="utf-8").replace('"', "")
    assert "title: 学完后端" in 正文
    assert "horizon: long" in 正文
    assert "status: paused" in 正文


def test_目标详情有证据卡(临时工作区, 站):
    请求(站, "POST", "/goals/new", 表单={"token": 令牌(站), "title": "学完后端基础"})
    造记录("接通 OAuth，卡点为 state 参数签名", 档=2, 目标="学完后端基础")
    造记录("给同学讲了 JWT 刷新", 档=3, 目标="学完后端基础")
    造记录("读了两章文档", 档=0, 目标="学完后端基础")

    状态, 页面, _ = 请求(站, "GET", "/goals/" + urllib.parse.quote("学完后端基础"))
    assert 状态 == 200
    assert "3 条记录" in 页面
    assert "能讲" in 页面 and "产出" in 页面
    assert "给同学讲" in 页面
    assert "完成度" not in 页面 and "进度条" not in 页面 and "连续" not in 页面


# ── M1：记录列表 / 单条编辑 ──────────────────────────────────


def test_记录列表按月分组并能筛选(临时工作区, 站):
    造记录("十一月的记录", 天前=1, 档=2)
    造记录("很久以前的一条", 天前=40, 档=0)

    _, 页面, _ = 请求(站, "GET", "/entries")
    assert "十一月的记录" in 页面
    assert "很久以前的一条" in 页面
    assert "共 2 条" in 页面

    _, 只要产出, _ = 请求(站, "GET", 查询("/entries", 档位="2"))
    assert "十一月的记录" in 只要产出
    assert "很久以前的一条" not in 只要产出

    _, 只要情感, _ = 请求(站, "GET", 查询("/entries", 部分="emotion"))
    assert "十一月的记录" not in 只要情感


def test_单条页面能看到全部字段(临时工作区, 站):
    编号 = 造记录("接通 OAuth，卡点为 state 参数签名", 档=2)
    状态, 页面, _ = 请求(站, "GET", f"/entries/{编号}")
    assert 状态 == 200
    assert "接通 OAuth" in 页面
    assert "OAuth" in 页面
    assert "改这一条" in 页面


def test_在页面上改一句话(临时工作区, 站):
    编号 = 造记录("旧的那句话")

    状态, _, _ = 请求(
        站, "POST", f"/entries/{编号}",
        表单={"token": 令牌(站), "did": "新的那句话，带 state 参数签名",
              "level": "3", "outcome": "stuck", "status": "settled"},
    )
    assert 状态 in (200, 303)

    条目 = store.读条目(store.找条目文件(编号))
    assert 条目["did"] == "新的那句话，带 state 参数签名"
    assert 条目["level"] == 3
    assert 条目["outcome"] == "stuck"


def test_超过60字会被拒并保留输入(临时工作区, 站):
    编号 = 造记录("正常的一句")
    太长 = "啊" * 70

    状态, 页面, _ = 请求(
        站, "POST", f"/entries/{编号}",
        表单={"token": 令牌(站), "did": 太长, "level": "2", "outcome": "done", "status": "settled"},
    )
    assert 状态 == 200
    assert "超过 60 字" in 页面
    assert 太长 in 页面, "被拒之后要把用户刚填的内容留在框里"
    assert store.读条目(store.找条目文件(编号))["did"] == "正常的一句"


def test_记录id带路径穿越会404(临时工作区, 站):
    for 坏 in ("../../../etc/passwd", "..%2F..%2Fsecret", "a%2Fb"):
        状态, _, _ = 请求(站, "GET", f"/entries/{坏}")
        assert 状态 == 404, f"{坏} 居然没被拦住"


# ── M2：提问 / 章节 / 画像 / 回顾 / 设置 ─────────────────────


def test_提问页只看召回不调模型(临时工作区, 站):
    造记录("面试前失眠，觉得自己什么都准备不好", 天前=40, 档=0, 部分="emotion")
    造记录("又崩了", 天前=20, 档=0, 部分="emotion")

    状态, 页面, _ = 请求(站, "GET", 查询("/ask", q="我好累", dry="1"))
    assert 状态 == 200
    assert "翻到的旧记录" in 页面
    assert "失眠" in 页面


def test_提问页能出回答(临时工作区, 站, monkeypatch):
    造记录("接通 OAuth，卡点为 state 参数签名", 天前=40)

    def 假调用(*a, **k):
        return llm.模型回复(
            文本="你在 2026-10-16 卡在 state 参数签名上，这次要不要先只看报错？",
            输入token=10, 输出token=5, 模型名="测试", 降级到第几级=3,
        )

    monkeypatch.setattr(llm, "调用", 假调用)

    状态, 页面, _ = 请求(站, "GET", 查询("/ask", q="我又卡住了"))
    assert 状态 == 200
    assert "2026-10-16" in 页面
    assert "只看报错" in 页面


def test_章节页(临时工作区, 站):
    状态, 空页面, _ = 请求(站, "GET", "/chapters")
    assert 状态 == 200
    assert "还没有章节" in 空页面

    章节 = store.新建章节(title="OAuth 调试", entry_count=2, level_max=2)
    store.写章节(章节)
    造记录("接通 OAuth", 档=2, 章节="OAuth 调试")

    _, 页面, _ = 请求(站, "GET", "/chapters")
    assert "OAuth 调试" in 页面

    _, 详情, _ = 请求(站, "GET", "/chapters/" + urllib.parse.quote("OAuth 调试"))
    assert "接通 OAuth" in 详情


def test_画像页显示最近一份(临时工作区, 站):
    _, 空页面, _ = 请求(站, "GET", "/portrait")
    assert "还没有生成过" in 空页面

    目录 = 临时工作区 / "vault" / "portrait"
    目录.mkdir(parents=True, exist_ok=True)
    (目录 / "2026-Q4.md").write_text(
        "## 2026-Q4\n\n### 我现在的假设\n\n- 我猜你会先缩起来。（依据：3 次类似场景）\n",
        encoding="utf-8",
    )

    _, 页面, _ = 请求(站, "GET", "/portrait")
    assert "2026-Q4" in 页面
    assert "先缩起来" in 页面
    assert "life portrait" in 页面


def test_回顾页给出数据和命令(临时工作区, 站):
    造记录("本周的一条", 天前=1)
    _, 页面, _ = 请求(站, "GET", "/review")
    assert "最近七天" in 页面
    assert "证据分布" in 页面
    assert "life review --week" in 页面


def test_设置页显示路径和模型(临时工作区, 站):
    _, 页面, _ = 请求(站, "GET", "/settings")
    assert "数据目录" in 页面
    assert "vault" in 页面
    assert "抽取模型" in 页面


# ── 安全与边界 ───────────────────────────────────────────────


def test_外部域名打到本机会被拒(临时工作区, 站):
    状态, 页面, _ = 请求(站, "GET", "/", 主机="evil.example.com")
    assert 状态 == 403
    assert "Host 不对" in 页面


def test_假令牌什么也改不了(临时工作区, 站):
    状态, 页面, _ = 请求(
        站, "POST", "/goals/new", 表单={"token": "假的", "title": "被塞进来的目标"}
    )
    assert 状态 == 403
    assert "令牌不对" in 页面
    assert not (临时工作区 / "vault" / "goals" / "被塞进来的目标.md").exists()


def test_别的网站提交也不行(临时工作区, 站):
    状态, 页面, _ = 请求(
        站, "POST", "/add",
        表单={"token": 令牌(站), "text": "跨站塞进来的"},
        来源="https://evil.example.com",
    )
    assert 状态 == 403
    assert "不是从本页面提交" in 页面


def test_用户写的尖括号会被转义(临时工作区, 站):
    造记录("<script>alert(1)</script> 调通了 XSS")
    _, 页面, _ = 请求(站, "GET", "/entries")
    assert "<script>alert(1)</script>" not in 页面
    assert "&lt;script&gt;" in 页面


def test_所有页面都没有外部资源(临时工作区, 站):
    造记录("一条记录")
    造记录("待确认的一条", 状态="needs_review")
    请求(站, "POST", "/goals/new", 表单={"token": 令牌(站), "title": "某个目标"})

    路径们 = [
        "/", "/entries", "/ask", "/goals", "/goals/new", "/chapters",
        "/portrait", "/review", "/settings",
    ]
    for 路径 in 路径们:
        状态, 页面, _ = 请求(站, "GET", 路径)
        assert 状态 == 200, f"{路径} 状态是 {状态}"
        for 禁令 in ("<link", "<script src", "@import", 'src="http', 'href="http'):
            assert 禁令 not in 页面, f"{路径} 里有外部资源：{禁令}"


def test_不存在的页面有友好提示(临时工作区, 站):
    状态, 页面, _ = 请求(站, "GET", "/no-such-page")
    assert 状态 == 404
    assert "没有这个页面" in 页面
    assert "回今天" in 页面


def test_浏览器发来_null_来源时不该误伤(临时工作区, 站, 假抽取):
    """有些浏览器/隐私设置会发 Origin: null。那不是攻击，不该拦。"""
    状态, 页面, _ = 请求(
        站, "POST", "/add",
        表单={"token": 令牌(站), "text": "用 null 来源提交的一条记录"},
        来源="null",
    )
    assert 状态 in (200, 303), 页面
    assert list((临时工作区 / "vault" / "now").rglob("*.md")), "正常提交被拦了"


def test_不带来源的提交也能用(临时工作区, 站, 假抽取):
    """某些情况下浏览器不带 Origin/Referer；令牌才是主要防线。"""
    状态, 页面, _ = 请求(
        站, "POST", "/add", 表单={"token": 令牌(站), "text": "没有 Origin 的一条记录"}
    )
    assert 状态 in (200, 303), 页面


def test_本服务自己的来源能正常提交(临时工作区, 站, 假抽取):
    """Origin 必须精确等于本服务地址；写成前缀判断会放过别的端口，写成漏配会误伤自己。"""
    来源 = f"http://127.0.0.1:{站}"
    状态, 页面, _ = 请求(
        站, "POST", "/add",
        表单={"token": 令牌(站), "text": "从本站提交的一条记录"},
        来源=来源,
    )
    assert 状态 in (200, 303), 页面
    assert list((临时工作区 / "vault" / "now").rglob("*.md"))


def test_别的端口的来源会被拒(临时工作区, 站):
    状态, _, _ = 请求(
        站, "POST", "/add",
        表单={"token": 令牌(站), "text": "从别的端口来的"},
        来源="http://127.0.0.1:1",
    )
    assert 状态 == 403


# ── 上传：图片与文件 ─────────────────────────────────────────

PNG1像素 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
    b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def 多段(字段: dict, 文件=None, 边界="----lifeTestBoundary"):
    段 = []
    for 键, 值 in 字段.items():
        段.append(
            f"--{边界}\r\nContent-Disposition: form-data; name=\"{键}\"\r\n\r\n{值}\r\n".encode("utf-8")
        )
    if 文件:
        名, 数据 = 文件
        段.append(
            (
                f"--{边界}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{名}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8")
            + 数据
            + b"\r\n"
        )
    段.append(f"--{边界}--\r\n".encode("utf-8"))
    return b"".join(段), f"multipart/form-data; boundary={边界}"


def 造docx(正文: str) -> bytes:
    import io
    import zipfile

    内存 = io.BytesIO()
    with zipfile.ZipFile(内存, "w") as 包:
        包.writestr("[Content_Types].xml", "<Types/>")
        包.writestr(
            "word/document.xml",
            f"<w:document><w:body><w:p><w:r><w:t>{正文}</w:t></w:r></w:p></w:body></w:document>",
        )
    return 内存.getvalue()


@pytest.fixture()
def 假看图(monkeypatch):
    """图片抽取：返回 OCR 全文 + 摘要 + 一条 claim。"""

    def 调用(任务名, 系统提示, 用户内容, **kw):
        import json

        return llm.模型回复(
            文本=json.dumps(
                {
                    "ocr_text": "报错原文：KeyError 'chapter'\n第 218 行",
                    "digest": "终端截图：一个 KeyError",
                    "entries": [
                        {
                            "did": "修掉 KeyError chapter，pop 没给默认值",
                            "body": "修掉 KeyError chapter，pop 没给默认值",
                            "part": "record",
                            "minutes": 0,
                            "outcome": "done",
                            "anchors": {"tech": ["KeyError"], "people": [], "link": ""},
                            "emotion": {"valence": 0, "arousal": 0.3, "trigger": "", "quote": ""},
                            "level": 2,
                            "goal": "",
                            "blockers": [],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            输入token=1, 输出token=1, 模型名="测试", 降级到第几级=1,
        )

    monkeypatch.setattr(llm, "调用", 调用)


def test_传一张图片能记下一条(临时工作区, 站, 假看图):
    体, 类型 = 多段({"token": 令牌(站)}, 文件=("截图.png", PNG1像素))
    状态, 页面, _ = 请求(站, "POST", "/add", 原始=体, 类型=类型)
    assert 状态 in (200, 303), 页面

    文件们 = list((临时工作区 / "vault" / "now").rglob("*.md"))
    assert len(文件们) == 1

    # OCR 全文必须留下（原图删掉之后，这是那张图唯一的话）
    全文文件 = list((临时工作区 / "vault" / "media").glob("*.md"))
    assert 全文文件, "media 里应该有一份 OCR 全文"
    正文 = 全文文件[0].read_text(encoding="utf-8")
    assert "KeyError" in 正文
    assert "终端截图" in 正文

    # 原图默认不留
    暂存图 = list((临时工作区 / "vault" / "inbox" / "图片暂存").glob("*"))
    assert not 暂存图, "原图应该被删掉"


def test_勾了保留原文件才留原图(临时工作区, 站, 假看图):
    体, 类型 = 多段({"token": 令牌(站), "keep": "1"}, 文件=("截图.png", PNG1像素))
    状态, 页面, _ = 请求(站, "POST", "/add", 原始=体, 类型=类型)
    assert 状态 in (200, 303), 页面

    留在media = [f for f in (临时工作区 / "vault" / "media").glob("*.png")]
    assert 留在media, "勾了保留就该留下原图"


def test_传一个txt能吸进正文(临时工作区, 站, 假抽取):
    内容 = "今天把接口调通了，卡在 state 参数签名。\n调了三个小时。".encode("utf-8")
    体, 类型 = 多段({"token": 令牌(站)}, 文件=("笔记.txt", 内容))
    状态, 页面, _ = 请求(站, "POST", "/add", 原始=体, 类型=类型)
    assert 状态 in (200, 303), 页面

    全文 = list((临时工作区 / "vault" / "media").glob("*.md"))
    assert 全文 and "state 参数签名" in 全文[0].read_text(encoding="utf-8")
    assert list((临时工作区 / "vault" / "now").rglob("*.md"))


def test_传一个docx能抽出文字(临时工作区, 站, 假抽取):
    体, 类型 = 多段({"token": 令牌(站)}, 文件=("周报.docx", 造docx("本周完成了检索模块的初版")))
    状态, 页面, _ = 请求(站, "POST", "/add", 原始=体, 类型=类型)
    assert 状态 in (200, 303), 页面

    全文 = list((临时工作区 / "vault" / "media").glob("*.md"))
    assert 全文 and "检索模块" in 全文[0].read_text(encoding="utf-8")


def test_不支持的文件类型会明确拒绝(临时工作区, 站, 假抽取):
    体, 类型 = 多段({"token": 令牌(站)}, 文件=("合同.pdf", b"%PDF-1.4 ..."))
    状态, 页面, _ = 请求(站, "POST", "/add", 原始=体, 类型=类型)
    assert 状态 == 400
    assert "不支持这种文件" in 页面
    assert not list((临时工作区 / "vault" / "now").rglob("*.md")), "被拒的文件不该产生记录"


def test_文件名带路径也越不出去(临时工作区, 站, 假抽取):
    体, 类型 = 多段({"token": 令牌(站)}, 文件=("../../evil.txt", "外面的内容".encode("utf-8")))
    状态, _, _ = 请求(站, "POST", "/add", 原始=体, 类型=类型)
    assert 状态 in (200, 303)
    # 落盘名一律是自己的 id，不会出现 evil.txt 这种文件
    越界 = [p for p in (临时工作区).rglob("evil.txt")]
    assert not 越界


def test_名字像图片但内容不是图片会被拒(临时工作区, 站, 假抽取):
    体, 类型 = 多段({"token": 令牌(站)}, 文件=("假的.png", "这不是图片".encode("utf-8")))
    状态, 页面, _ = 请求(站, "POST", "/add", 原始=体, 类型=类型)
    assert 状态 == 400
    assert "内容不像图片" in 页面


def test_太大的文件会被拒(临时工作区, 站):
    巨大 = b"\x89PNG\r\n\x1a\n" + b"0" * (9 * 1024 * 1024)
    体, 类型 = 多段({"token": 令牌(站)}, 文件=("大图.png", 巨大))
    状态, 页面, _ = 请求(站, "POST", "/add", 原始=体, 类型=类型)
    assert 状态 == 400
    assert "太大" in 页面


# ── 补记过去（同一个「记一条」表单，多一个「什么时候」）──


def test_首页有时间输入框(临时工作区, 站):
    _, 页面, _ = 请求(站, "GET", "/")
    assert 'name="when"' in 页面
    assert "不填就是现在" in 页面


def test_网页上能补记过去的事(临时工作区, 站, 假抽取):
    状态, 页面, _ = 请求(
        站, "POST", "/add",
        表单={"token": 令牌(站), "text": "大一做的图书管理系统", "when": "2023-09"},
    )
    assert 状态 in (200, 303), 页面

    文件 = list((临时工作区 / "vault" / "now" / "2023-09").glob("*.md"))
    assert 文件
    条目 = store.读条目(文件[0])
    assert 条目["when"] == "2023-09"


def test_网页上记不清日期也能记(临时工作区, 站, 假抽取):
    状态, 页面, _ = 请求(
        站, "POST", "/add",
        表单={"token": 令牌(站), "text": "大一做的图书管理系统", "when": "大一"},
    )
    assert 状态 in (200, 303), 页面
    条目 = store.读条目(next((临时工作区 / "vault" / "now").rglob("*.md")))
    assert 条目["when"] == "大一"
    assert "时间不详" in 页面


def test_网页上写未来日期会被拒(临时工作区, 站, 假抽取):
    状态, 页面, _ = 请求(
        站, "POST", "/add", 表单={"token": 令牌(站), "text": "未来的事", "when": "2099-01"}
    )
    assert 状态 == 400
    assert "未来" in 页面


def test_首页说明可以写以前做过的项目(临时工作区, 站):
    """用户的原话：在「今天做了什么」那里要能看出「以前的项目也可以写」。"""
    _, 页面, _ = 请求(站, "GET", "/")
    assert "以前做过的项目也写这里" in 页面
    assert "做了什么、用了什么、卡在哪" in 页面
    assert "你会这个" in 页面


def test_单条页可以改什么时候(临时工作区, 站):
    """日期填错了要能自己改，不用去手改 markdown。"""
    编号 = 造记录("大一做的图书管理系统")
    状态, 页面, _ = 请求(
        站, "POST", f"/entries/{编号}",
        表单={"token": 令牌(站), "did": "大一做的图书管理系统", "level": "2",
              "outcome": "done", "status": "settled", "when": "大一"},
    )
    assert 状态 in (200, 303), 页面
    assert store.读条目(store.找条目文件(编号))["when"] == "大一"


# ── 后台任务：长任务也能点按钮（docs/WEBUI.md §2.6）────────────


def _等任务(端口, 任务号, 最多秒: float = 6):
    """轮询任务页，直到它不再是「正在跑」。"""
    import time

    for _ in range(int(最多秒 * 20)):
        状态, 页面, _ = 请求(端口, "GET", f"/jobs/{任务号}")
        if "正在跑" not in 页面:
            return 状态, 页面
        time.sleep(0.05)
    return 状态, 页面


def test_章节页有归纳按钮和提名处理(临时工作区, 站, monkeypatch):
    from life import promote

    monkeypatch.setattr(
        promote,
        "提名",
        lambda **k: {"主题数": 1, "提名": [{"标题": "OAuth 调试", "摘要": "跨两个月", "条数": 3, "月份": ["2026-10", "2026-11"]}],
                     "没提名": [], "说明": ""},
    )
    _, 页面, _ = 请求(站, "GET", "/chapters")
    assert 'action="/jobs/settle"' in 页面
    assert "归纳最近的记录" in 页面


def test_点按钮能跑归纳任务(临时工作区, 站, monkeypatch):
    from life import promote

    monkeypatch.setattr(
        promote,
        "提名",
        lambda **k: {"主题数": 2, "提名": [], "没提名": [], "说明": ""},
    )
    状态, _, 位置 = 请求(站, "POST", "/jobs/settle", 表单={"token": 令牌(站)})
    assert 状态 == 303
    assert 位置.startswith("/jobs/")

    任务号 = 位置.rsplit("/", 1)[-1]
    状态, 页面 = _等任务(站, 任务号)
    assert 状态 == 200
    assert "完成" in 页面
    assert "找到 2 个主题" in 页面


def test_任务失败时显示原因并能重试(临时工作区, 站, monkeypatch):
    from life import portrait

    def 炸(**k):
        raise RuntimeError("模型不听话")

    monkeypatch.setattr(portrait, "生成", 炸)

    状态, _, 位置 = 请求(站, "POST", "/jobs/portrait", 表单={"token": 令牌(站)})
    assert 状态 == 303
    任务号 = 位置.rsplit("/", 1)[-1]

    _, 页面 = _等任务(站, 任务号)
    assert "模型不听话" in 页面
    assert 'action="/jobs/portrait"' in 页面  # 重试按钮


def test_画像页有生成按钮(临时工作区, 站):
    _, 页面, _ = 请求(站, "GET", "/portrait")
    assert 'action="/jobs/portrait"' in 页面
    assert "生成" in 页面


def test_设置页有重建索引按钮(临时工作区, 站):
    _, 页面, _ = 请求(站, "GET", "/settings")
    assert 'action="/jobs/reindex"' in 页面


def test_认识不了的任务名给404(临时工作区, 站):
    状态, 页面, _ = 请求(
        站, "POST", "/jobs/" + urllib.parse.quote("乱写"), 表单={"token": 令牌(站)}
    )
    assert 状态 == 404
    assert "没有这种任务" in 页面


def test_同一个任务不会叠着跑(临时工作区, 站, monkeypatch):
    from life import jobs

    monkeypatch.setattr(jobs, "_正在跑", {"settle": "fake1"})
    monkeypatch.setattr(jobs, "_任务表", {"fake1": jobs.任务(id="fake1", 动作="settle", 名称="归纳最近的记录")})

    状态, _, 位置 = 请求(站, "POST", "/jobs/settle", 表单={"token": 令牌(站)})
    assert 状态 == 303
    assert 位置 == "/jobs/fake1", "已经在跑就直接进那个任务页，不该起第二个"


def test_有没抽成的记录时首页给补抽按钮(临时工作区, 站):
    """断网/模型出错留下的 inbox，页面上要能一键补抽。"""
    体, 类型 = 多段({"token": 令牌(站), "text": "断网时记的一条"})
    # 直接往 inbox 写一条，模拟「抽取失败留在队列里」
    store.写inbox(
        {
            "格式": 1,
            "id": "20261125-220000",
            "ts": store.时间文本(store.现在()),
            "kind": "text",
            "原文": "断网时记的一条",
            "部分": "record",
            "private": False,
            "keep_image": False,
            "图片": "",
            "图片原名": "",
            "when": "",
            "内容指纹": "假指纹",
            "尝试次数": 0,
            "最后错误": "模拟失败",
        }
    )

    _, 页面, _ = 请求(站, "GET", "/")
    assert "还没抽成" in 页面
    assert 'action="/jobs/retry"' in 页面
