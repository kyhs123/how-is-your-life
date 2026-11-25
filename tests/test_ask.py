"""测对话——通过 `life ask` 看屏幕上说了什么、以及它有没有照规矩重试。

模型那一层打桩（不联网、不花钱），但断言只看用户能看到的东西。
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from life import cli, index, llm, store

运行 = CliRunner()


def _记一条(did: str, *, 天前: int = 1, tech: list[str] | None = None) -> None:
    from datetime import timedelta

    时间 = (store.现在() - timedelta(days=天前)).replace(microsecond=0)
    条目 = store.新建条目(
        id=时间.strftime("%Y%m%d-%H%M%S"),
        ts=store.时间文本(时间),
        did=did,
        body=did,
        level=2,
        anchors={"tech": tech or [], "people": [], "link": ""},
    )
    store.写条目(条目)
    连接 = index.连接索引()
    try:
        index.写入条目(连接, 条目)
    finally:
        连接.close()


def _钉住模型(答案们: list[str]):
    """按顺序返回这些回答，并记下被调了几次。"""
    次数 = {"n": 0}

    def 调用(*args, **kwargs):
        i = min(次数["n"], len(答案们) - 1)
        次数["n"] += 1
        return llm.模型回复(
            文本=答案们[i], 输入token=100, 输出token=50, 模型名="测试", 降级到第几级=1
        )

    return 调用, 次数


def test_合规的回答会直接显示出来(临时工作区, monkeypatch):
    _记一条("接通 OAuth，卡点为 state 参数签名", 天前=40, tech=["OAuth"])

    调用, _ = _钉住模型([
        "你在 2026-10-16 卡在 state 参数签名上，最后靠读源码解决。要不要今晚只抄一段报错？"
    ])
    monkeypatch.setattr(llm, "调用", 调用)

    结果 = 运行.invoke(cli.app, ["ask", "我又卡住了"])
    assert 结果.exit_code == 0, 结果.output
    assert "读源码" in 结果.output
    assert "没做到" not in 结果.output


def test_空泛安慰会被退回重写一次(临时工作区, monkeypatch):
    _记一条("接通 OAuth，卡点为 state 参数签名", 天前=40)

    调用, 次数 = _钉住模型([
        "你已经很棒了，相信自己！",
        "你在 2026-10-16 卡在 state 参数签名，后来靠读源码解决了。要不先只看报错？",
    ])
    monkeypatch.setattr(llm, "调用", 调用)

    结果 = 运行.invoke(cli.app, ["ask", "我好累"])
    assert 次数["n"] == 2, "不合格应该重写一次"
    assert "读源码" in 结果.output
    assert "你已经很棒了" not in 结果.output


def test_两次都不合格就照实告诉用户(临时工作区, monkeypatch):
    _记一条("接通 OAuth，卡点为 state 参数签名", 天前=40)

    调用, _ = _钉住模型(["你已经很棒了。", "一切都会好的，加油。"])
    monkeypatch.setattr(llm, "调用", 调用)

    结果 = 运行.invoke(cli.app, ["ask", "我好累"])
    assert 结果.exit_code == 0
    assert "硬要求没做到" in 结果.output
    assert "空泛安慰" in 结果.output


def test_回答里没有真实日期也会被点出来(临时工作区, monkeypatch):
    _记一条("接通 OAuth，卡点为 state 参数签名", 天前=40)

    调用, _ = _钉住模型(["你以前也解决过类似的问题，别担心。", "你以前也解决过类似的问题。"])
    monkeypatch.setattr(llm, "调用", 调用)

    结果 = 运行.invoke(cli.app, ["ask", "我又卡住了"])
    assert "日期" in 结果.output
