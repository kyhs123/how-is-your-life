"""测 board.py：看板能生成、能自包含、会藏私密、不会被用户输入弄坏。"""

from __future__ import annotations

from life import board, store


def _写一条(编号: str, ts: str = "2026-11-25T14:32:00+08:00", **改):
    字段 = {
        "id": 编号,
        "ts": ts,
        "part": "record",
        "did": "接通 OAuth 登录，卡点为 state 参数签名",
        "minutes": 240,
        "outcome": "done",
        "anchors": {"tech": ["OAuth"], "people": [], "link": ""},
        "emotion": {"valence": -0.4, "arousal": 0.6, "trigger": "文档不清", "quote": "文档写得跟屎一样"},
        "level": 2,
        "blockers": ["state 参数要签名"],
        "status": "settled",
    }
    字段.update(改)
    return store.写条目(store.新建条目(**字段))


def test_生成的文件里有记录内容(临时工作区):
    路径 = _写一条("20261125-143200")
    文件, 统计 = board.生成()

    assert 文件.exists()
    assert 统计["条数"] == 1
    assert 统计["档位"][2] == 1

    正文 = 文件.read_text(encoding="utf-8")
    assert "接通 OAuth 登录" in 正文
    assert "产出" in 正文  # 证据档的中文名
    assert "state 参数要签名" in 正文  # 卡点
    assert 路径.exists()


def test_页面是单文件自包含的(临时工作区):
    """不允许任何外链：断网、换电脑、三个月后翻出来都得能看。"""
    _写一条("20261125-143200")
    文件, _ = board.生成()
    正文 = 文件.read_text(encoding="utf-8")

    for 禁令 in ('<link', '<script src', '@import', 'src="http', "src='http"):
        assert 禁令 not in 正文, f"页面里出现了外部资源：{禁令}"


def test_私密记录默认不显示(临时工作区):
    _写一条("20261125-143200")
    _写一条("20261125-143201", did="这句只存本地", private=True)

    默认文件, 默认统计 = board.生成()
    默认正文 = 默认文件.read_text(encoding="utf-8")
    assert 默认统计["条数"] == 1
    assert 默认统计["隐去的私密条数"] == 1
    assert "这句只存本地" not in 默认正文

    全量文件, 全量统计 = board.生成(含私密=True)
    全量正文 = 全量文件.read_text(encoding="utf-8")
    assert 全量统计["条数"] == 2
    assert "这句只存本地" in 全量正文
    assert "别发给别人" in 全量正文


def test_一条记录都没有也能生成(临时工作区):
    文件, 统计 = board.生成()
    assert 文件.exists()
    assert 统计["条数"] == 0
    assert "还没有任何记录" in 文件.read_text(encoding="utf-8")


def test_记录里的尖括号不会把页面弄坏(临时工作区):
    """用户写的内容要转义，否则一个 < 就能毁掉整个页面。"""
    _写一条("20261125-143200", did="<script>alert(1)</script> 调通了 XSS")
    文件, _ = board.生成()
    正文 = 文件.read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in 正文
    assert "&lt;script&gt;" in 正文


def test_情绪点按时间排序(临时工作区):
    早 = store.新建条目(
        id="20261101-100000",
        ts="2026-11-01T10:00:00+08:00",
        did="第一天，很慌",
        body="第一天，很慌",
        part="emotion",
        emotion={"valence": -0.8, "arousal": 0.7, "trigger": "", "quote": ""},
    )
    晚 = store.新建条目(
        id="20261120-100000",
        ts="2026-11-20T10:00:00+08:00",
        did="第二十天，好多了",
        body="第二十天，好多了",
        part="emotion",
        emotion={"valence": 0.6, "arousal": 0.4, "trigger": "", "quote": ""},
    )
    点 = board.情绪点([晚, 早])  # 故意乱序传进去
    assert [值 for _, 值 in 点] == [-0.8, 0.6]
