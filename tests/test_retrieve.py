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
    秒: int = 0,
    valence: float = 0.0,
    level: int = 2,
    private: bool = False,
    tech: list[str] | None = None,
    people: list[str] | None = None,
    when: str = "",
) -> None:
    时间 = (store.现在() - timedelta(days=天前) + timedelta(seconds=秒)).replace(
        microsecond=0
    )
    条目 = store.新建条目(
        id=时间.strftime("%Y%m%d-%H%M%S"),
        ts=store.时间文本(时间),
        did=did,
        body=did,
        level=level,
        when=when,
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


def test_问我是什么样的人会去挑代表性记录(临时工作区):
    """这类问题字面上跟任何记录都不像（实测三路全 0 命中）。

    所以要有一条「代表性」检索：档位高的优先，而不是只给最近三条。
    """
    _造("今天买了瓶水", 天前=0, level=0)
    _造("独立完成 STM32 竞速小车整车软硬件", 天前=0, level=2)

    输出 = _试("你觉得我是个什么样的人")

    assert "代表性记录" in 输出
    assert "STM32" in 输出


def test_召回列表显示人话时间而不是时间戳(临时工作区):
    """给模型看的日期必须是 when（「大学期间」），不是 ts。

    实测没过这一条时，模型会说「你的记录里全是 2026-11-25 这一天」。
    """
    _造("用 ctypes 调机械臂 SDK", 天前=0, level=2, when="大学期间")

    输出 = _试("你觉得我是个什么样的人")

    assert "大学期间" in 输出


def test_问我这周做了什么会按时间翻出这一周(临时工作区):
    """用户的原话：想知道最近一周做了什么，直接在提问里问就行。

    这条最容易被做错：记录里没人写过「这周」三个字，文字检索全空，
    最后只能兜底给最近三条——那不叫回答。
    """
    周几 = store.现在().weekday()  # 0 = 周一。用相对本周的偏移，哪天跑都稳
    _造("把 OAuth 调通了", 天前=周几, level=2)
    _造("改了一遍简历", 天前=周几, 秒=1, level=1)
    _造("上周的事：读了两章 Docker 文档", 天前=周几 + 7)

    输出 = _试("我这周都做了什么")

    assert "这周" in 输出, "要走到「按时间段」这一路"
    assert "OAuth" in 输出 and "简历" in 输出
    assert "Docker" not in 输出, "上周的不能算进这周"


def test_最近几天能收紧到窗口里(临时工作区):
    _造("昨天把接口接上了", 天前=1)
    _造("二十天前搬了一次家", 天前=20)

    输出 = _试("最近三天我都干了什么")

    assert "接口接上了" in 输出
    assert "搬家" not in 输出


def test_补记的旧事不算进这周(临时工作区):
    """ts 是「补记那天」。不挡的话，问「这周做了什么」会把整份简历都算成这周做的事。"""
    _造("这周真做的：把 OAuth 调通了", 天前=0)
    _造("简历里的事：独立完成 STM32 竞速小车", 天前=0, 秒=1, when="大学期间")

    输出 = _试("我这周都做了什么")

    assert "OAuth" in 输出
    assert "STM32" not in 输出
