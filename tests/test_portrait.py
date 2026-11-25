"""测画像——`life portrait` 生成的文件长什么样、以及「假设必须带依据」这条硬要求。"""

from __future__ import annotations

from typer.testing import CliRunner

from life import cli, llm

运行 = CliRunner()


def _记一条(标题: str) -> None:
    运行.invoke(cli.app, ["add", 标题, "--demo"])


def _钉住(文本: str):
    def 调用(*args, **kwargs):
        return llm.模型回复(
            文本=文本, 输入token=10, 输出token=5, 模型名="测试", 降级到第几级=3
        )

    return 调用


合规 = """## 2026-Q4

### 我现在的假设

- 我猜你在卡住时会先怀疑自己。（依据：3 次类似场景）

### 相对上季度的变化

- ~~拖延型~~ → 不是拖延，是对别人安排的事没动力。（依据：4 次）
"""


def test_没有记录时不生成画像(临时工作区):
    结果 = 运行.invoke(cli.app, ["portrait"])
    assert 结果.exit_code == 1
    assert "先记几条" in 结果.output


def test_生成的文件里有假设和变化两块(临时工作区, monkeypatch):
    _记一条("今天把 OAuth 调通了，卡在 state 参数签名")
    monkeypatch.setattr(llm, "调用", _钉住(合规))

    结果 = 运行.invoke(cli.app, ["portrait"])
    assert 结果.exit_code == 0, 结果.output
    assert "画像已生成" in 结果.output

    画像 = list((临时工作区 / "vault" / "portrait").glob("*.md"))
    assert 画像, "画像文件没生成"
    正文 = 画像[0].read_text(encoding="utf-8")
    assert "我现在的假设" in 正文
    assert "相对上季度的变化" in 正文
    assert "~~拖延型~~" in 正文, "被推翻的旧假设要用删除线留着"


def test_假设没写依据会被点出来(临时工作区, monkeypatch):
    """§4.7 的验收项：每条假设都要带「依据：N 次类似场景」。"""
    _记一条("今天读完了两章 Docker 文档")
    monkeypatch.setattr(
        llm,
        "调用",
        _钉住("## 2026-Q4\n\n### 我现在的假设\n\n- 你是一个很努力的人。\n"),
    )

    结果 = 运行.invoke(cli.app, ["portrait"])
    assert 结果.exit_code == 0
    assert "没写依据" in 结果.output
    assert "很努力" in 结果.output


def test_diff只看变化那一块(临时工作区, monkeypatch):
    _记一条("今天读完了两章 Docker 文档")
    monkeypatch.setattr(llm, "调用", _钉住(合规))
    运行.invoke(cli.app, ["portrait"])

    结果 = 运行.invoke(cli.app, ["portrait", "--diff"])
    assert 结果.exit_code == 0
    assert "拖延型" in 结果.output
    assert "我现在的假设" not in 结果.output


def test_模型返回空内容时不写空白文件(临时工作区, monkeypatch):
    """思考型模型 token 用光时正文是空的，这时候绝不能留下一个空画像。"""
    _记一条("今天读完了两章 Docker 文档")
    monkeypatch.setattr(llm, "调用", _钉住("   "))

    结果 = 运行.invoke(cli.app, ["portrait"])
    assert 结果.exit_code == 1
    assert "空内容" in 结果.output
    assert not list((临时工作区 / "vault" / "portrait").glob("*.md"))
