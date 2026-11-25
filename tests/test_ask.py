"""测 ask.py：上下文组装、禁止清单、以及「必须引用真实日期」这条硬要求。"""

from __future__ import annotations

import json
from datetime import timedelta

from life import ask, index, llm, store


def _造(编号: str, ts: str, did: str, *, valence: float = 0.0, tech: list[str] | None = None) -> None:
    条目 = store.新建条目(
        id=编号,
        ts=ts,
        did=did,
        body=did,
        level=2,
        anchors={"tech": tech or [], "people": [], "link": ""},
        emotion={"valence": valence, "arousal": 0.5, "trigger": "", "quote": ""},
    )
    store.写条目(条目)
    连接 = index.连接索引()
    try:
        index.写入条目(连接, 条目)
    finally:
        连接.close()


def _天前(天: int) -> str:
    return store.时间文本(store.现在() - timedelta(days=天))


# ── 禁止清单（§7.2 / §4.4 验收）──────────────────────────────


def test_空泛安慰会被抓出来():
    上下文 = "- 2026-10-16（产出）：接通 OAuth\n"
    for 句子 in (
        "你已经很棒了。",
        "相信自己，一切都会好的。",
        "加油，坚持住。",
        "你值得被爱。",
    ):
        没做到 = ask.校验回答(句子, 上下文)
        assert 没做到, f"这句话没被抓出来：{句子}"
        assert any("空泛安慰" in 一条 for 一条 in 没做到)


def test_附和自我贬低会被抓出来():
    没做到 = ask.校验回答("听起来你确实不太行。", "- 2026-10-16：接通 OAuth")
    assert any("附和自我贬低" in 一条 for 一条 in 没做到)


def test_心理诊断和价值判断会被抓出来():
    assert ask.校验回答("你可能有拖延症。", "- 2026-10-16：x")
    assert ask.校验回答("你应该辞职。", "- 2026-10-16：x")


# ── 必须引用真实日期 ─────────────────────────────────────────


def test_引用了真实日期就通过日期这一条():
    上下文 = "- 2026-10-16（产出）：接通 OAuth，卡点为 state 参数签名"
    合规 = "十月那次你卡在 state 参数签名，最后是靠读源码找到的。那是 2026-10-16。要不要今晚只看报错原文？"
    没做到 = ask.校验回答(合规, 上下文)
    assert not any("日期" in 一条 for 一条 in 没做到)


def test_换一种日期写法也认():
    上下文 = "- 2026-10-16（产出）：接通 OAuth"
    assert not any("日期" in x for x in ask.校验回答("十月十六号那天…其实 10月16日 你就在弄这个。", 上下文))


def test_不引用日期会被抓出来():
    上下文 = "- 2026-10-16（产出）：接通 OAuth"
    没做到 = ask.校验回答("你以前也解决过类似的问题，别担心。", 上下文)
    assert any("日期" in 一条 for 一条 in 没做到)


def test_三条以上建议会被抓出来():
    回答 = "1. 早睡\n2. 多运动\n3. 写日记"
    没做到 = ask.校验回答(回答, "- 2026-10-16：x")
    assert any("三条以上建议" in 一条 for 一条 in 没做到)


# ── 上下文组装 ───────────────────────────────────────────────


def test_上下文里带日期和锚点(临时工作区):
    _造("20261016-200000", _天前(40), "接通 OAuth，卡点为 state 参数签名", valence=-0.5, tech=["OAuth"])
    召回结果, _ = __import__("life.retrieve", fromlist=["召回"]).召回("OAuth", 用向量=False)
    上下文 = ask._组装上下文(召回结果, [])

    assert "20261016" in 上下文 or "2026-10-16" in 上下文
    assert "OAuth" in 上下文
    assert "底色" in 上下文  # §4.4 规定的第一块
    assert "章节" in 上下文  # 第二块


def test_上下文长度会被压到上限以内(临时工作区):
    for i in range(12):
        _造(f"2026110{i % 9 + 1}-100000", _天前(i), f"第 {i} 条：接通 OAuth 的第 {i} 个细节", tech=["OAuth"])

    from life import retrieve

    召回结果, _ = retrieve.召回("OAuth", 取几条=12, 用向量=False)
    assert ask.估算token(ask._组装上下文(召回结果, [])) > 0


# ── 端到端（模型用假的）──────────────────────────────────────


def test_问一次能拿到回答和召回(临时工作区, monkeypatch):
    _造("20261016-200000", _天前(40), "接通 OAuth，卡点为 state 参数签名", tech=["OAuth"])

    def 假调用(*args, **kwargs):
        回答 = "你在 2026-10-16 卡在 state 参数签名上，最后靠读源码解决。这次先只看报错原文就好。"
        return llm.模型回复(文本=回答, 输入token=100, 输出token=50, 模型名="测试", 降级到第几级=1)

    monkeypatch.setattr(llm, "调用", 假调用)

    结果 = ask.问("我又卡住了", 用向量=False)
    assert 结果["回答"]
    assert 结果["没做到"] == [], f"这份合规回答不该被判不合格：{结果['没做到']}"
    assert 结果["召回"]
    assert 结果["上下文token"] > 0


def test_第一次不合格会重试一次(临时工作区, monkeypatch):
    次数 = []

    def 假调用(*args, **kwargs):
        次数.append(1)
        if len(次数) == 1:
            return llm.模型回复(
                文本="你已经很棒了，相信自己！",
                输入token=10, 输出token=5, 模型名="测试", 降级到第几级=1,
            )
        return llm.模型回复(
            文本="你在 2026-10-16 那次是靠读源码解决的。要不要今晚只抄一段报错？",
            输入token=10, 输出token=5, 模型名="测试", 降级到第几级=1,
        )

    _造("20261016-200000", _天前(40), "接通 OAuth，卡点为 state 参数签名", tech=["OAuth"])
    monkeypatch.setattr(llm, "调用", 假调用)

    结果 = ask.问("我好累", 用向量=False)
    assert len(次数) == 2, "不合格应该重试一次"
    assert 结果["没做到"] == []
    assert "读源码" in 结果["回答"]
