"""测回顾——`life review` 的输出，用户能看到的东西。"""

from __future__ import annotations

from typer.testing import CliRunner

from life import cli, llm

运行 = CliRunner()


def _记一条(标题: str) -> None:
    运行.invoke(cli.app, ["add", 标题, "--demo"])


def test_本周回顾有五块内容(临时工作区, monkeypatch):
    _记一条("今天把 OAuth 调通了，卡在 state 参数签名")

    def 假调用(*args, **kwargs):
        return llm.模型回复(
            文本="## 这段时间做了什么\n\n调通了 OAuth。\n\n## 下周一个建议\n\n今晚只看报错。",
            输入token=10,
            输出token=5,
            模型名="测试",
            降级到第几级=3,
        )

    monkeypatch.setattr(llm, "调用", 假调用)

    结果 = 运行.invoke(cli.app, ["review", "--week"])
    assert 结果.exit_code == 0, 结果.output
    assert "的回顾" in 结果.output
    assert "证据分布" in 结果.output
    assert "和上一段比" in 结果.output
    assert "下周一个建议" in 结果.output


def test_没有记录时明确告诉你(临时工作区):
    结果 = 运行.invoke(cli.app, ["review", "--week"])
    assert 结果.exit_code == 1
    assert "没有记录" in 结果.output


def test_连不上模型也出得来数据(临时工作区, monkeypatch):
    """回顾不能因为模型挂了就什么都看不到。"""
    _记一条("今天读完了两章 Docker 文档")

    def 断网(*args, **kwargs):
        raise llm.网络错误("模拟断网")

    monkeypatch.setattr(llm, "调用", 断网)

    结果 = 运行.invoke(cli.app, ["review", "--week"])
    assert 结果.exit_code == 0, 结果.output
    assert "证据分布" in 结果.output
    assert "没连上模型" in 结果.output


def test_html是单文件可以直接打开(临时工作区, monkeypatch):
    _记一条("今天把 OAuth 调通了")
    _记一条("晚上跑了个 5 公里")

    def 假调用(*args, **kwargs):
        return llm.模型回复(
            文本="## 这段时间做了什么\n\n- 调通 OAuth\n- 跑了 5 公里",
            输入token=10,
            输出token=5,
            模型名="测试",
            降级到第几级=3,
        )

    monkeypatch.setattr(llm, "调用", 假调用)

    输出文件 = 临时工作区 / "回顾.html"
    结果 = 运行.invoke(cli.app, ["review", "--week", "--html", "--out", str(输出文件)])
    assert 结果.exit_code == 0, 结果.output
    assert 输出文件.exists()

    正文 = 输出文件.read_text(encoding="utf-8")
    assert "<!doctype html>" in 正文
    assert "调通 OAuth" in 正文
    for 禁令 in ("<link", "<script src", "@import", 'src="http'):
        assert 禁令 not in 正文, f"页面里出现了外部资源：{禁令}"
