"""测导出——全部通过 `life export`，看磁盘上出现了什么文件、里面写了什么。"""

from __future__ import annotations

import itertools
from datetime import timedelta

from typer.testing import CliRunner

from life import cli, index, llm, store

运行 = CliRunner()
序号 = itertools.count()  # 同一秒里造两条会撞 id（id 就是时间戳），所以每条错开一秒


def _造(did: str, *, 天前: int = 0, 档: int = 2, private: bool = False, 技术=()) -> None:
    时间 = (store.现在() - timedelta(days=天前) + timedelta(seconds=next(序号))).replace(
        microsecond=0
    )
    条目 = store.新建条目(
        id=时间.strftime("%Y%m%d-%H%M%S"),
        ts=store.时间文本(时间),
        did=did,
        body=did,
        level=档,
        private=private,
        anchors={"tech": list(技术), "people": [], "link": ""},
    )
    store.写条目(条目)
    连接 = index.连接索引()
    try:
        index.写入条目(连接, 条目)
    finally:
        连接.close()


def _假模型(monkeypatch, 回答: str, 收到: list | None = None) -> None:
    def 调用(任务名, 系统提示, 用户内容, **kw):
        if 收到 is not None:
            收到.append({"系统": 系统提示, "用户": 用户内容})
        return llm.模型回复(
            文本=回答, 输入token=100, 输出token=200, 模型名="测试", 降级到第几级=1
        )

    monkeypatch.setattr(llm, "调用", 调用)


def _导出文件(工作区) -> list:
    return sorted((工作区 / "vault" / "导出").glob("*")) if (工作区 / "vault" / "导出").exists() else []


def test_没有模板的话就从要求里认(临时工作区):
    """用户会说人话（「我要发微博关于我的人生」），不用记模板名。"""
    for 要求, 想要 in (
        ("我要应聘机器人相关的工作，帮我生成一份简历", "简历"),
        ("我要发微博关于我的人生，帮我概括一下", "微博"),
        ("面试要用，帮我写个自我介绍", "自我介绍"),
        ("给导师的周报", "周报"),
        ("把这几条整理成一份给朋友看的东西", "通用"),
    ):
        结果 = 运行.invoke(cli.app, ["export", 要求, "--dry-run"])
        assert 结果.exit_code == 0, 结果.output
        assert f"模板：{想要}" in 结果.output, f"「{要求}」认成了别的模板：{结果.output}"


def test_干跑不调模型也不写文件(临时工作区, monkeypatch):
    _造("独立完成 STM32 竞速小车整车软硬件", 档=2)

    def 不该被调用(*args, **kwargs):
        raise AssertionError("干跑不该调模型")

    monkeypatch.setattr(llm, "调用", 不该被调用)
    结果 = 运行.invoke(cli.app, ["export", "帮我生成一份简历", "--dry-run"])

    assert 结果.exit_code == 0, 结果.output
    assert "STM32" in 结果.output, "干跑要能看见挑了什么素材"
    assert not _导出文件(临时工作区), "干跑不能写文件"


def test_导出按钮会写出一份文件(临时工作区, monkeypatch):
    _造("独立完成 STM32 竞速小车整车软硬件", 档=2, 技术=["STM32", "PCB"])
    _造("和岗位无关的一条：今天没睡好", 档=0)
    收到: list[dict] = []
    _假模型(monkeypatch, "# 张三\n\n## 项目\n- 独立完成 STM32 竞速小车", 收到)

    结果 = 运行.invoke(cli.app, ["export", "我要应聘机器人相关的工作，帮我生成一份简历"])

    assert 结果.exit_code == 0, 结果.output
    文件们 = _导出文件(临时工作区)
    assert len(文件们) == 1
    assert 文件们[0].suffix == ".md"
    assert 文件们[0].name.endswith("-简历.md")
    正文 = 文件们[0].read_text(encoding="utf-8")
    assert "STM32 竞速小车" in 正文
    assert "模板：简历" in 正文, "抬头要写清用了哪个模板"

    发给模型 = 收到[0]["用户"]
    assert "STM32" in 发给模型
    assert "简历" in 收到[0]["系统"], "用的应该是简历那份指导文档"


def test_私密记录不会进导出素材(临时工作区, monkeypatch):
    _造("公开的一条：调通 OAuth", 档=2)
    _造("私密的一条：老板找我谈话", 档=3, private=True)
    收到: list[dict] = []
    _假模型(monkeypatch, "一份东西", 收到)

    运行.invoke(cli.app, ["export", "帮我生成一份简历"])
    发给模型 = 收到[0]["用户"]
    assert "调通 OAuth" in 发给模型
    assert "老板找我谈话" not in 发给模型


def test_编造的数字会被标在文件最前面(临时工作区, monkeypatch):
    """模型最爱干的事：给它三条记录，它能写出「获得 3 项专利、效率提升 40%」。"""
    _造("独立完成 STM32 竞速小车整车软硬件", 档=2)
    _假模型(monkeypatch, "# 张三\n\n获得 3 项专利，效率提升 40%")

    结果 = 运行.invoke(cli.app, ["export", "帮我生成一份简历"])

    assert 结果.exit_code == 0, 结果.output
    正文 = _导出文件(临时工作区)[0].read_text(encoding="utf-8")
    抬头 = 正文.split("\n\n")[1]
    assert "⚠️" in 抬头 and "3" in 抬头 and "40" in 抬头
    assert "自己核" in 抬头
    assert "3" in 结果.output and "40" in 结果.output, "命令行上也要提醒"


def test_什么都没说会报错(临时工作区):
    结果 = 运行.invoke(cli.app, ["export", "   "])
    assert 结果.exit_code == 1
    assert "你还没说要导出成什么" in 结果.output


def test_模板名写错会说有哪些(临时工作区):
    结果 = 运行.invoke(cli.app, ["export", "随便", "--template", "小作文"])
    assert 结果.exit_code == 1
    assert "简历" in 结果.output and "微博" in 结果.output
