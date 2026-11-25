"""测索引——用户能感知的两件事：索引删了能重建；坏文件不拖垮其它记录。"""

from __future__ import annotations

from typer.testing import CliRunner

from life import cli

运行 = CliRunner()


def _记一条(标题: str) -> None:
    运行.invoke(cli.app, ["add", 标题, "--demo"])


def test_索引删掉之后能重建(临时工作区):
    _记一条("今天把 OAuth 调通了，卡在 state 参数签名")

    索引文件 = 临时工作区 / "vault" / "index.sqlite"
    assert 索引文件.exists()
    索引文件.unlink()  # 模拟「索引被删了」

    结果 = 运行.invoke(cli.app, ["reindex"])
    assert 结果.exit_code == 0
    assert "扫描 1 个记录文件，成功写入索引 1 条" in 结果.output


def test_一个文件坏了不影响其它文件(临时工作区):
    _记一条("今天读完了两章 Docker 文档")
    坏文件 = 临时工作区 / "vault" / "now" / "2026-11" / "坏的.md"
    坏文件.parent.mkdir(parents=True, exist_ok=True)
    坏文件.write_text("这里根本不是一条记录", encoding="utf-8")

    结果 = 运行.invoke(cli.app, ["reindex"])
    assert 结果.exit_code == 0
    assert "成功写入索引 1 条" in 结果.output
    assert "没读进来" in 结果.output
