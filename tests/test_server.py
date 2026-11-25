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


def 请求(端口, 方法, 路径, *, 表单=None, 主机=None, 来源=None):
    连接 = http.client.HTTPConnection("127.0.0.1", 端口, timeout=20)
    头, 体 = {}, None
    if 表单 is not None:
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
