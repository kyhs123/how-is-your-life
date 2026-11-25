"""测 retrieve.py：三路检索各自能不能捞到该捞的东西，以及私密记录绝不出现。"""

from __future__ import annotations

from datetime import timedelta

from life import index, retrieve, store


def _造(
    编号: str,
    ts: str,
    did: str,
    *,
    valence: float = 0.0,
    part: str = "record",
    level: int = 2,
    private: bool = False,
    tech: list[str] | None = None,
    people: list[str] | None = None,
    quote: str = "",
) -> None:
    """写一条记录，同时进 md 和索引。测试里造数据统一走这里。"""
    条目 = store.新建条目(
        id=编号,
        ts=ts,
        did=did,
        body=did,
        part=part,
        level=level,
        private=private,
        anchors={"tech": tech or [], "people": people or [], "link": ""},
        emotion={"valence": valence, "arousal": 0.5, "trigger": "", "quote": quote},
    )
    store.写条目(条目)
    连接 = index.连接索引()
    try:
        index.写入条目(连接, 条目)
    finally:
        连接.close()


def _天前(天: int) -> str:
    时间 = store.现在() - timedelta(days=天)
    return store.时间文本(时间)


def test_结构路能翻出一个月前的难受(临时工作区):
    """§4.3 的验收：输入「我好累」，要能返回 30 天前那条负面记录。

    注意这条记录的 did 里根本没有「累」字——靠的是 SQL 的情绪条件，不是文字匹配。
    """
    _造("20261016-200000", _天前(40), "面试前失眠，觉得自己什么都准备不好", valence=-0.8, part="emotion")
    _造("20261120-100000", _天前(5), "把接口调通了，松口气", valence=0.6)

    结果, 诊断 = retrieve.召回("我好累", 用向量=False)

    assert 结果, "结构检索没捞到任何东西"
    最早的 = 结果[0]
    assert "失眠" in 最早的["did"]
    assert "结构" in 最早的["来源"]
    assert "情绪极点" in 诊断["结构走了哪几条"]


def test_私密记录在任何一路都不出现(临时工作区):
    """§4.3 / §8：private 的记录检索不到。"""
    _造(
        "20261124-100000",
        _天前(1),
        "私密：老板找我谈话，我很难受",
        valence=-0.9,
        private=True,
        tech=["老板"],
    )
    _造("20261125-100000", _天前(0), "公开的一条：调通了 OAuth", tech=["OAuth"])

    for 查询 in ("老板", "难受", "私密", "谈话"):
        结果, _ = retrieve.召回(查询, 用向量=False)
        assert all(not e["private"] for e in 结果), f"「{查询}」把私密记录捞出来了"
        assert all("私密" not in e["did"] for e in 结果)


def test_全文路能按技术名找到(临时工作区):
    _造("20261125-100000", _天前(0), "调通 OAuth，卡在 state 参数签名", tech=["OAuth"])
    _造("20261125-110000", _天前(0), "读了两章 Docker 文档")

    结果, 诊断 = retrieve.召回("OAuth", 用向量=False)
    assert any("OAuth" in e["did"] for e in 结果)
    assert 诊断["各路"]["全文"] >= 1


def test_不到三个字也能搜到(临时工作区):
    """trigram 分词要求 3 个字，短词得退回普通包含匹配，否则中文单字/双字词全废。"""
    _造("20261125-100000", _天前(0), "和导师聊毕设方向", people=["导师"])

    结果, 诊断 = retrieve.召回("导师", 用向量=False)
    assert any("导师" in e["did"] for e in 结果)
    assert any("包含匹配" in 提示 for 提示 in 诊断["提示"])


def test_两路同时命中会排在前面(临时工作区):
    """RRF 合并：被多路捞到的记录应该比只被一路捞到的排前面。"""
    _造(
        "20261125-100000",
        _天前(0),
        "调通 OAuth，但折腾到凌晨很难受",
        valence=-0.7,
        tech=["OAuth"],
    )
    _造("20261001-100000", _天前(55), "另一次崩溃，和 OAuth 无关", valence=-0.8)
    _造("20261101-100000", _天前(24), "无关的一条正面记录", valence=0.5)

    结果, _ = retrieve.召回("OAuth 我好累", 用向量=False)
    assert 结果
    assert "OAuth" in 结果[0]["did"]
    assert len(结果[0]["来源"]) >= 2, "两路都该命中这条"


def test_三路全空时给最近几条(临时工作区):
    """完全没有文字线索时，至少给最近几条，让对话有上下文可用。"""
    _造("20261120-100000", _天前(5), "第一条")
    _造("20261125-100000", _天前(0), "第二条")

    结果, _ = retrieve.召回("完全不相关的一句话", 用向量=False)
    assert 结果, "三路全空时也应该兜底给最近的记录"


def test_最近几天只取时间窗内的(临时工作区):
    _造("20261101-100000", _天前(24), "很久以前")
    _造("20261125-100000", _天前(0), "刚刚")

    最近 = retrieve.最近几天(3)
    assert any("刚刚" in e["did"] for e in 最近)
    assert all("很久以前" not in e["did"] for e in 最近)
