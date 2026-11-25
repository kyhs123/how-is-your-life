"""测检索——全部通过 `life ask --dry-run`，看屏幕上给出了什么。

这样测的是「用户敲这条命令，能不能看到该看到的东西」，不是内部怎么算分。
"""

from __future__ import annotations

from datetime import timedelta

from typer.testing import CliRunner

from life import cli, index, store

运行 = CliRunner()


def _造(
    did: str,
    *,
    天前: int,
    valence: float = 0.0,
    level: int = 2,
    private: bool = False,
    tech: list[str] | None = None,
    people: list[str] | None = None,
) -> None:
    时间 = (store.现在() - timedelta(days=天前)).replace(microsecond=0)
    条目 = store.新建条目(
        id=时间.strftime("%Y%m%d-%H%M%S"),
        ts=store.时间文本(时间),
        did=did,
        body=did,
        level=level,
        part="emotion" if valence < -0.7 else "record",
        private=private,
        anchors={"tech": tech or [], "people": people or [], "link": ""},
        emotion={"valence": valence, "arousal": 0.5, "trigger": "", "quote": ""},
    )
    store.写条目(条目)
    连接 = index.连接索引()
    try:
        index.写入条目(连接, 条目)
    finally:
        连接.close()


def _试(查询: str) -> str:
    return 运行.invoke(cli.app, ["ask", 查询, "--dry-run"]).output


def test_说我好累能翻出一个月前的难受(临时工作区):
    """§4.3 的验收项。注意那条记录的 did 里根本没有「累」字。"""
    _造("面试前失眠，觉得自己什么都准备不好", 天前=40, valence=-0.85)
    _造("把接口调通了，松口气", 天前=5, valence=0.6)

    输出 = _试("我好累")

    assert "情绪极点" in 输出
    assert "失眠" in 输出


def test_口语化的说法也能翻出旧账(临时工作区):
    _造("面试前失眠，觉得自己什么都准备不好", 天前=55, valence=-0.85)

    for 说法 in ("我心里堵得慌", "最近有点 emo", "破防了"):
        输出 = _试(说法)
        assert "情绪极点" in 输出, f"「{说法}」没触发情绪检索"
        assert "失眠" in 输出, f"「{说法}」没翻出那条记录"


def test_按技术名能搜到(临时工作区):
    _造("调通 OAuth，卡在 state 参数签名", 天前=3, tech=["OAuth"])
    _造("读了两章 Docker 文档", 天前=2)

    输出 = _试("OAuth")
    assert "OAuth" in 输出
    assert "全文" in 输出


def test_按人名能搜到(临时工作区):
    _造("和导师聊毕设方向", 天前=3, people=["导师"])

    输出 = _试("导师")
    assert "导师" in 输出


def test_问怎么做恢复会去找低谷之后的事(临时工作区):
    _造("又崩了，觉得自己半年什么都没做成", 天前=55, valence=-0.9)
    _造("还是爬起来把 Docker Compose 写完了", 天前=53, valence=0.3)

    输出 = _试("那次之后我是怎么恢复的")
    assert "低谷之后怎么恢复" in 输出
    assert "Docker" in 输出


def test_私密记录一条都不出现(临时工作区):
    _造("老板找我谈话，我很难受", 天前=1, valence=-0.9, private=True, tech=["老板"])
    _造("公开的一条：调通 OAuth", 天前=0, tech=["OAuth"])

    for 查询 in ("老板", "难受", "谈话", "我好累"):
        输出 = _试(查询)
        assert "老板找我谈话" not in 输出, f"「{查询}」把私密记录捞出来了"


def test_什么都没搜到时也给几条最近的(临时工作区):
    _造("第一条", 天前=5)
    _造("第二条", 天前=0)

    输出 = _试("完全不相关的一句话")
    assert "一条都没召回到" not in 输出
