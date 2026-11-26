"""测固化与晋升——同样只从命令行进、从文件和屏幕出。

模型那一层打桩（AGENTS.md 允许的唯一例外：不联网、不花钱、几秒跑完），
但断言全部看用户能看到的东西：章节文件、记录的 chapter 字段、changelog。
"""

from __future__ import annotations

import json
from datetime import timedelta

from typer.testing import CliRunner

from life import cli, index, llm, store

运行 = CliRunner()


def _记一条(did: str, *, 天前: int, level: int = 2, link: str = "") -> str:
    时间 = (store.现在() - timedelta(days=天前)).replace(microsecond=0)
    编号 = 时间.strftime("%Y%m%d-%H%M%S")
    条目 = store.新建条目(
        id=编号,
        ts=store.时间文本(时间),
        did=did,
        body=did,
        level=level,
        anchors={"tech": ["OAuth"], "people": [], "link": link},
    )
    store.写条目(条目)
    连接 = index.连接索引()
    try:
        index.写入条目(连接, 条目)
    finally:
        连接.close()
    return 编号


def _假模型(主题们: list[dict]):
    """让模型固定返回这些主题。只换掉网络那一层。"""

    def 调用(*args, **kwargs):
        return llm.模型回复(
            文本=json.dumps({"themes": 主题们}, ensure_ascii=False),
            输入token=100,
            输出token=50,
            模型名="测试",
            降级到第几级=1,
        )

    return 调用


def test_记录太少就不折腾模型(临时工作区, monkeypatch):
    def 不许调用(*args, **kwargs):
        raise AssertionError("记录太少时不该调用模型")

    monkeypatch.setattr(llm, "调用", 不许调用)
    _记一条("只记了一条", 天前=1)

    结果 = 运行.invoke(cli.app, ["settle", "--week"])
    assert 结果.exit_code == 0
    assert "太少" in 结果.output


def test_够条件的主题会被提名并写进changelog(临时工作区, monkeypatch):
    一 = _记一条("接通 OAuth，卡点为 state 参数签名", 天前=40)
    二 = _记一条("又调 OAuth，这次卡在 state 签名", 天前=30)
    三 = _记一条("OAuth 终于通了，卡点是 state 参数", 天前=1)
    四 = _记一条("OAuth 的 state 参数又要重签一次", 天前=2)

    monkeypatch.setattr(
        llm,
        "调用",
        _假模型([
            {
                "title": "OAuth 调试", "keywords": ["OAuth"],
                "entry_ids": [三, 四],
                "has_artifact": True,
                "artifact": "PR #12",
                "summary": "跨两个月，在 OAuth 上卡了三次，最后靠读源码解决。",
            }
        ]),
    )

    结果 = 运行.invoke(cli.app, ["settle", "--week"])
    assert 结果.exit_code == 0, 结果.output
    assert "提名：OAuth 调试" in 结果.output

    日志 = (临时工作区 / "vault" / "changelog.md").read_text(encoding="utf-8")
    assert "提名：OAuth 调试 → 主题" in 日志
    assert "PR #12" in 日志

    # settle 只提名，不能动记录
    条目 = store.读条目(next((临时工作区 / "vault" / "now").rglob("*.md")))
    assert 条目["chapter"] == ""


def test_条件不够的不提名(临时工作区, monkeypatch):
    """只有 1 条记录 / 只在 1 个月出现 → 不满足 §3.2，不提名。"""
    一 = _记一条("OAuth 通了", 天前=1)
    二 = _记一条("OAuth 又修了一下", 天前=2)

    monkeypatch.setattr(
        llm,
        "调用",
        _假模型([{"title": "OAuth 调试", "keywords": ["OAuth"], "entry_ids": [一, 二], "has_artifact": True, "artifact": "", "summary": ""}]),
    )

    结果 = 运行.invoke(cli.app, ["settle", "--week"])
    assert "暂不提名" in 结果.output
    assert "跨 ≥2 个月" in 结果.output or "≥3 条" in 结果.output
    assert "√ 提名：OAuth 调试" not in 结果.output


def test_确认之后章节文件生成且记录被回填(临时工作区, monkeypatch):
    一 = _记一条("接通 OAuth，卡点为 state 参数签名", 天前=40)
    二 = _记一条("又调 OAuth，这次卡在 state 签名", 天前=30)
    三 = _记一条("OAuth 终于通了", 天前=1)
    四 = _记一条("OAuth 又要重签 state 参数", 天前=2)

    monkeypatch.setattr(
        llm,
        "调用",
        _假模型([{"title": "OAuth 调试", "keywords": ["OAuth"], "entry_ids": [三, 四], "has_artifact": True, "artifact": "PR #12", "summary": "卡了三次，靠读源码解决。"}]),
    )
    运行.invoke(cli.app, ["settle", "--week"])

    结果 = 运行.invoke(cli.app, ["promote", "--yes"])
    assert 结果.exit_code == 0, 结果.output

    章节文件 = 临时工作区 / "vault" / "chapters" / "OAuth 调试.md"
    assert 章节文件.exists()
    正文 = 章节文件.read_text(encoding="utf-8")
    assert "entry_count: 4" in 正文
    assert "level_max: 2" in 正文

    # 每条记录的 chapter 字段要指向这个章节（§4.6 的验收项）
    所有条目 = [store.读条目(p) for p in (临时工作区 / "vault" / "now").rglob("*.md")]
    assert all(e["chapter"] == "OAuth 调试" for e in 所有条目)

    日志 = (临时工作区 / "vault" / "changelog.md").read_text(encoding="utf-8")
    assert "晋升 OAuth 调试：当下 → 主题「OAuth 调试」" in 日志
    assert "依据：" in 日志


def test_拒绝之后不再重复提同一条(临时工作区, monkeypatch):
    一 = _记一条("接通 OAuth", 天前=40)
    二 = _记一条("OAuth 又卡了", 天前=30)
    三 = _记一条("OAuth 通了", 天前=1)
    四 = _记一条("OAuth 的 state 参数又改了一次", 天前=2)

    主题 = [{"title": "OAuth 调试", "keywords": ["OAuth"], "entry_ids": [三, 四], "has_artifact": True, "artifact": "", "summary": ""}]
    monkeypatch.setattr(llm, "调用", _假模型(主题))

    运行.invoke(cli.app, ["settle", "--week"])
    拒绝 = 运行.invoke(cli.app, ["promote"], input="n\n")
    assert 拒绝.exit_code == 0
    assert "拒绝了" in 拒绝.output
    assert "章节" not in 拒绝.output or "拒绝" in 拒绝.output

    # 再跑一次 settle：同一条不该再被提名
    再跑 = 运行.invoke(cli.app, ["settle", "--week"])
    assert "暂不提名" in 再跑.output
    assert "你之前拒绝过" in 再跑.output
    assert "√ 提名：OAuth 调试" not in 再跑.output


def test_没有提名时promote说清楚(临时工作区):
    结果 = 运行.invoke(cli.app, ["promote"])
    assert 结果.exit_code == 0
    assert "没有等你处理的提名" in 结果.output
