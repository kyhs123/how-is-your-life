"""测 index.py：建表、写入、从 markdown 完整重建、记账。"""

from __future__ import annotations

from life import index, store


def _造条目(id="20261125-143200", ts="2026-11-25T14:32:00+08:00", **改):
    字段 = {
        "id": id,
        "ts": ts,
        "part": "record",
        "did": "接通 OAuth 登录，卡点为 state 参数签名",
        "minutes": 240,
        "outcome": "done",
        "anchors": {"tech": ["OAuth"], "people": [], "link": ""},
        "emotion": {"valence": -0.5, "arousal": 0.6, "trigger": "文档不清", "quote": ""},
        "level": 2,
        "goal": "",
        "blockers": [],
        "private": False,
        "status": "settled",
        "body": "接通 OAuth 登录，卡点为 state 参数签名。",
    }
    字段.update(改)
    return store.新建条目(**字段)


def test_写入一条后能查到(临时工作区):
    连接 = index.连接索引()
    try:
        index.写入条目(连接, _造条目())
        行 = 连接.execute("SELECT id, did, level FROM entries").fetchone()
        assert 行["id"] == "20261125-143200"
        assert "OAuth" in 行["did"]
        assert 行["level"] == 2
    finally:
        连接.close()


def test_全文索引能搜到(临时工作区):
    连接 = index.连接索引()
    try:
        index.写入条目(连接, _造条目())
        命中 = 连接.execute(
            "SELECT entry_id FROM entries_fts WHERE entries_fts MATCH ?", ("OAuth",)
        ).fetchall()
        assert [行["entry_id"] for 行 in 命中] == ["20261125-143200"]
    finally:
        连接.close()


def test_同一个id写两次不会变成两条(临时工作区):
    连接 = index.连接索引()
    try:
        index.写入条目(连接, _造条目())
        index.写入条目(连接, _造条目(did="改过的内容，锚点 OAuth"))
        assert 连接.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 1
        assert 连接.execute("SELECT COUNT(*) FROM entries_fts").fetchone()[0] == 1
    finally:
        连接.close()


def test_删掉索引也能从markdown完整重建(临时工作区):
    """DESIGN.md §3.5 的硬性验收项。"""
    条目 = _造条目()
    store.写条目(条目)

    连接 = index.连接索引()
    连接.close()
    index.库文件().unlink()  # 模拟「索引被删了」

    结果 = index.重建索引()
    assert 结果["扫描"] == 1
    assert 结果["成功"] == 1
    assert 结果["失败"] == []

    连接 = index.连接索引()
    try:
        assert index.统计(连接)["条目数"] == 1
    finally:
        连接.close()


def test_坏文件不挡住其它文件重建(临时工作区):
    好条目 = _造条目()
    store.写条目(好条目)
    坏文件 = store.确保vault就绪() / "now" / "2026-11" / "20260101-000000.md"
    坏文件.write_text("这里根本不是 markdown 记录", encoding="utf-8")

    结果 = index.重建索引()
    assert 结果["成功"] == 1
    assert len(结果["失败"]) == 1


def test_用量记账(临时工作区):
    连接 = index.连接索引()
    try:
        index.记录用量(连接, "extract", "某模型", 100, 50)
        数字 = index.统计(连接)
        assert 数字["总token"] == 150
        assert 数字["调用次数"] == 1
    finally:
        连接.close()
