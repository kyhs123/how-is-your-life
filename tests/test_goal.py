"""测目标功能——全部从命令行进、从屏幕和文件出（AGENTS.md 的测试三原则）。

不测 goal.py 里的私有函数怎么算，只测：敲命令 → 看到什么 → 磁盘上留下什么。
"""

from __future__ import annotations

from datetime import timedelta

from typer.testing import CliRunner

from life import cli, index, store

运行 = CliRunner()


def _记一条(did: str, *, 天前: int = 0, goal: str = "", level: int = 0, minutes: int = 0) -> None:
    """造一条记录（同时在 md 和索引里）。"""
    # 每条往前挪一秒，保证 id 不撞（id 精确到秒，同一秒里造两条会被覆盖成一条）
    _记一条.序号 = getattr(_记一条, "序号", 0) + 1
    时间 = (store.现在() - timedelta(days=天前, seconds=_记一条.序号)).replace(microsecond=0)
    编号 = 时间.strftime("%Y%m%d-%H%M%S")
    条目 = store.新建条目(
        id=编号,
        ts=store.时间文本(时间),
        did=did,
        body=did,
        goal=goal,
        level=level,
        minutes=minutes,
        anchors={"tech": ["X"], "people": [], "link": ""},
    )
    store.写条目(条目)
    连接 = index.连接索引()
    try:
        index.写入条目(连接, 条目)
    finally:
        连接.close()


def test_立了目标之后文件和列表都有(临时工作区):
    结果 = 运行.invoke(cli.app, ["goal", "add", "学完后端基础", "--horizon", "term", "--why", "想自己做网站"])
    assert 结果.exit_code == 0, 结果.output

    文件 = 临时工作区 / "vault" / "goals" / "学完后端基础.md"
    assert 文件.exists()
    assert "想自己做网站" in 文件.read_text(encoding="utf-8")

    列表 = 运行.invoke(cli.app, ["goal", "list"])
    assert "学完后端基础" in 列表.output
    assert "进行中" in 列表.output


def test_同名目标不让重复立(临时工作区):
    运行.invoke(cli.app, ["goal", "add", "学完后端基础"])
    结果 = 运行.invoke(cli.app, ["goal", "add", "学完后端基础"])
    assert 结果.exit_code == 1
    assert "已经有一个" in 结果.output


def test_证据卡数出条数和档位分布(临时工作区):
    运行.invoke(cli.app, ["goal", "add", "学完后端基础", "--horizon", "term"])
    _记一条("接通 OAuth，卡点为 state 参数签名", goal="学完后端基础", level=2, minutes=240)
    _记一条("给同学讲了 JWT 刷新", goal="学完后端基础", level=3, minutes=60)
    _记一条("读了两章 Docker 文档", goal="学完后端基础", level=0)

    结果 = 运行.invoke(cli.app, ["goal", "show", "1"])
    assert 结果.exit_code == 0, 结果.output
    assert "3 条记录" in 结果.output
    assert "能讲" in 结果.output and "产出" in 结果.output and "接触" in 结果.output
    assert "接通 OAuth" in 结果.output  # 举了具体例子
    # 设计禁止的东西：不能出现百分比
    assert "%" not in 结果.output


def test_只有接触级别的记录要说实话(临时工作区):
    """§4.5：全接触的话显示「以接触为主，缺少独立产出」。"""
    运行.invoke(cli.app, ["goal", "add", "学完后端基础"])
    _记一条("看了两章 Docker 文档", goal="学完后端基础", level=0)
    _记一条("学了 React 基础", goal="学完后端基础", level=0)

    结果 = 运行.invoke(cli.app, ["goal", "show", "学完后端基础"])
    assert "以接触为主，缺少独立产出" in 结果.output


def test_没有挂上记录时说清楚原因(临时工作区):
    运行.invoke(cli.app, ["goal", "add", "学完后端基础"])
    _记一条("和这个目标无关的一件事", goal="")

    结果 = 运行.invoke(cli.app, ["goal", "show", "1"])
    assert "还没挂上任何记录" in 结果.output


def test_标记完成之后文件里的状态会变(临时工作区):
    运行.invoke(cli.app, ["goal", "add", "学完后端基础"])
    _记一条("上线了一个小项目", goal="学完后端基础", level=2)

    结果 = 运行.invoke(cli.app, ["goal", "done", "1"])
    assert 结果.exit_code == 0
    assert "已完成" in 结果.output

    文件 = 临时工作区 / "vault" / "goals" / "学完后端基础.md"
    assert "status: done" in 文件.read_text(encoding="utf-8")


def test_停下目标时原因会写进文件(临时工作区):
    运行.invoke(cli.app, ["goal", "add", "学完后端基础"])
    结果 = 运行.invoke(cli.app, ["goal", "stop", "1", "--reason", "发现更想做前端"])
    assert 结果.exit_code == 0
    文件 = 临时工作区 / "vault" / "goals" / "学完后端基础.md"
    正文 = 文件.read_text(encoding="utf-8")
    assert "status: stopped" in 正文
    assert "发现更想做前端" in 正文
