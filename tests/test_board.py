"""测看板——通过 `life board` 看生成出来的那个 HTML 文件。

用户能感知的事：文件在不在、里面有没有我的记录、断网能不能打开、私密会不会漏。
"""

from __future__ import annotations

from typer.testing import CliRunner

from life import cli

运行 = CliRunner()


def _记一条(标题: str, *额外) -> None:
    运行.invoke(cli.app, ["add", 标题, "--demo", *额外])


def test_生成的文件里有我的记录(临时工作区):
    _记一条("今天把 OAuth 调通了，卡在 state 参数签名")

    结果 = 运行.invoke(cli.app, ["board"])
    assert 结果.exit_code == 0, 结果.output

    文件 = 临时工作区 / "vault" / "看板.html"
    assert 文件.exists()
    正文 = 文件.read_text(encoding="utf-8")
    assert "OAuth" in 正文
    assert "证据档位分布" in 正文


def test_页面不依赖任何外部资源(临时工作区):
    """断网、换电脑、三年后翻出来，这个文件都得能打开。"""
    _记一条("今天读完了两章 Docker 文档")
    运行.invoke(cli.app, ["board"])

    正文 = (临时工作区 / "vault" / "看板.html").read_text(encoding="utf-8")
    for 禁令 in ("<link", "<script src", "@import", 'src="http'):
        assert 禁令 not in 正文, f"页面里出现了外部资源：{禁令}"


def test_私密记录默认不显示(临时工作区):
    _记一条("公开的一件事：调通 OAuth")
    _记一条("这句只存本地，别给任何人看", "--private")

    结果 = 运行.invoke(cli.app, ["board"])
    assert "1 条私密记录没有显示" in 结果.output

    正文 = (临时工作区 / "vault" / "看板.html").read_text(encoding="utf-8")
    assert "只存本地" not in 正文

    加参数 = 运行.invoke(cli.app, ["board", "--include-private"])
    assert 加参数.exit_code == 0
    正文2 = (临时工作区 / "vault" / "看板.html").read_text(encoding="utf-8")
    assert "只存本地" in 正文2
    assert "别发给别人" in 正文2


def test_一条记录都没有也能生成(临时工作区):
    结果 = 运行.invoke(cli.app, ["board"])
    assert 结果.exit_code == 0
    assert "0 条记录" in 结果.output

    正文 = (临时工作区 / "vault" / "看板.html").read_text(encoding="utf-8")
    assert "还没有任何记录" in 正文


def test_记录里的尖括号不会把页面弄坏(临时工作区):
    """用户写的内容必须转义，否则一个 < 就能毁掉整个页面。"""
    运行.invoke(
        cli.app,
        ["add", "<script>alert(1)</script> 调通了 XSS", "--demo"],
    )
    运行.invoke(cli.app, ["board"])

    正文 = (临时工作区 / "vault" / "看板.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in 正文
    assert "&lt;script&gt;" in 正文
