"""测网页界面——真的起一个服务器，真的发 HTTP 请求，真的看磁盘上的文件变没变。

这就是「用户能感知到的事」：点一下按钮，目标文件里那一行变了。
"""

from __future__ import annotations

import http.client
import json
import re
import threading
import urllib.parse

import pytest

from life import server as server模块
from life import store


@pytest.fixture()
def 网站(临时工作区):
    """起一个真实的 HTTP 服务器（端口交给系统分配），测完关掉。"""
    服务器 = server模块.造服务器(0)
    端口 = 服务器.server_address[1]
    线程 = threading.Thread(target=服务器.serve_forever, daemon=True)
    线程.start()
    try:
        yield 端口
    finally:
        服务器.shutdown()
        服务器.server_close()


def _请求(端口: int, 方法: str, 路径: str, *, 表单: dict | None = None, 主机: str | None = None):
    连接 = http.client.HTTPConnection("127.0.0.1", 端口, timeout=10)
    头 = {}
    体 = None
    if 表单 is not None:
        体 = urllib.parse.urlencode(表单)
        头["Content-Type"] = "application/x-www-form-urlencoded"
    if 主机 is not None:
        头["Host"] = 主机
    连接.request(方法, 路径, body=体, headers=头)
    响应 = 连接.getresponse()
    内容 = 响应.read().decode("utf-8", errors="replace")
    连接.close()
    return 响应.status, 内容


def _取令牌(端口: int) -> str:
    _, 页面 = _请求(端口, "GET", "/")
    匹配 = re.search(r'name="csrf-token" content="([^"]+)"', 页面) or re.search(
        r'name="token" value="([^"]+)"', 页面
    )
    assert 匹配, "首页里没有表单令牌"
    return 匹配.group(1)


def _造待确认记录() -> str:
    """造一条 needs_review 的记录（模拟抽取时没把握的情况）。"""
    时间 = store.现在()
    编号 = 时间.strftime("%Y%m%d-%H%M%S")
    条目 = store.新建条目(
        id=编号, ts=store.时间文本(时间), did="很累，什么都不想做", body="很累，什么都不想做",
        status="needs_review", part="emotion",
    )
    store.写条目(条目)
    from life import index

    连接 = index.连接索引()
    try:
        index.写入条目(连接, 条目)
    finally:
        连接.close()
    return 编号


def test_首页能打开(临时工作区, 网站):
    状态, 页面 = _请求(网站, "GET", "/")

    assert 状态 == 200
    assert "你过得怎么样" in 页面
    assert "待确认的记录" in 页面
    assert "目标" in 页面


def test_在网页里新建目标(临时工作区, 网站):
    令牌 = _取令牌(网站)

    状态, _ = _请求(
        网站,
        "POST",
        "/goal/new",
        表单={"token": 令牌, "title": "学完后端基础", "horizon": "term", "why": "想自己做网站"},
    )
    assert 状态 in (200, 303)

    文件 = 临时工作区 / "vault" / "goals" / "学完后端基础.md"
    assert 文件.exists()
    正文 = 文件.read_text(encoding="utf-8")
    assert 'title: "学完后端基础"' in 正文
    assert "想自己做网站" in 正文

    # 首页上立刻能看到它
    _, 首页 = _请求(网站, "GET", "/")
    assert "学完后端基础" in 首页


def test_在网页里改目标(临时工作区, 网站):
    令牌 = _取令牌(网站)
    _请求(网站, "POST", "/goal/new", 表单={"token": 令牌, "title": "学完后端基础"})

    状态, _ = _请求(
        网站,
        "POST",
        "/goal/" + urllib.parse.quote("学完后端基础"),
        表单={"token": 令牌, "title": "学完后端", "horizon": "long", "why": "", "due": "2027-06-01",
              "status": "paused"},
    )
    assert 状态 in (200, 303)

    正文 = (临时工作区 / "vault" / "goals" / "学完后端基础.md").read_text(encoding="utf-8")
    assert 'title: "学完后端"' in 正文
    assert "horizon: long" in 正文
    assert "status: paused" in 正文
    assert "2027-06-01" in 正文


def test_确认一条待确认的记录(临时工作区, 网站):
    编号 = _造待确认记录()
    令牌 = _取令牌(网站)

    _, 首页 = _请求(网站, "GET", "/")
    assert "很累，什么都不想做" in 首页, "待确认的记录应该出现在首页"

    状态, _ = _请求(
        网站, "POST", f"/entry/{urllib.parse.quote(编号)}/settle", 表单={"token": 令牌}
    )
    assert 状态 in (200, 303)

    条目 = store.读条目(store.找条目文件(编号))
    assert 条目["status"] == "settled"

    _, 首页2 = _请求(网站, "GET", "/")
    assert "很累，什么都不想做" not in 首页2, "确认过的不该再留在待确认区"


def test_别的域名访问会被拒(临时工作区, 网站):
    """防 DNS rebinding：别人把自己的域名解析到 127.0.0.1 也打不进来。"""
    状态, 页面 = _请求(网站, "GET", "/", 主机="evil.example.com")
    assert 状态 == 403
    assert "Host 不对" in 页面


def test_没有令牌的表单会被拒(临时工作区, 网站):
    """防跨站提交：别的网页诱导你提交，令牌对不上。"""
    状态, 页面 = _请求(网站, "POST", "/goal/new", 表单={"token": "假的", "title": "被塞进来的目标"})
    assert 状态 == 403
    assert "令牌不对" in 页面
    assert not (临时工作区 / "vault" / "goals" / "被塞进来的目标.md").exists()


def test_私密记录不出现在网页上(临时工作区, 网站):
    _造待确认记录()
    时间 = store.现在()
    编号 = 时间.strftime("%Y%m%d-%H%M%S") + "-私密"
    条目 = store.新建条目(
        id=编号, ts=store.时间文本(时间), did="这句只存本地", body="这句只存本地",
        status="needs_review", private=True, part="emotion",
    )
    store.写条目(条目)
    from life import index

    连接 = index.连接索引()
    try:
        index.写入条目(连接, 条目)
    finally:
        连接.close()

    _, 首页 = _请求(网站, "GET", "/")
    assert "这句只存本地" not in 首页
