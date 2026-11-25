"""测 cli.py：真正敲命令时会发生什么（用 CliRunner 假装在敲）。"""

from __future__ import annotations

from typer.testing import CliRunner

from life import cli, llm, store

运行 = CliRunner()


def _条目文件(工作区):
    return sorted((工作区 / "vault" / "now").rglob("*.md"))


def test_add一条文字(临时工作区):
    结果 = 运行.invoke(cli.app, ["add", "今天把 OAuth 调通了，卡在 state 参数签名", "--demo"])

    assert 结果.exit_code == 0, 结果.output
    文件们 = _条目文件(临时工作区)
    assert len(文件们) == 1

    条目 = store.读条目(文件们[0])
    assert "OAuth" in 条目["did"]
    assert 条目["status"] == "settled"
    assert len(条目["did"]) <= 60


def test_重复提交只留一条(临时工作区):
    for _ in range(2):
        结果 = 运行.invoke(cli.app, ["add", "今天把爬虫的反爬绕过去了", "--demo"])
        assert 结果.exit_code == 0

    assert len(_条目文件(临时工作区)) == 1
    assert "已经记过了" in 结果.output


def test_什么都不输入会报错并退出(临时工作区):
    结果 = 运行.invoke(cli.app, ["add", ""])
    assert 结果.exit_code == 1
    assert "什么都没输入" in 结果.output


def test_断网时录入仍然成功(临时工作区, monkeypatch):
    """DESIGN.md C5 / §4.1 的验收项：退出码 0，内容留在 inbox 等重试。"""

    def 断网(*args, **kwargs):
        raise llm.网络错误("模拟断网")

    monkeypatch.setattr(llm, "调用", 断网)
    monkeypatch.setattr(cli.config, "读取任务", lambda 任务名: object())

    结果 = 运行.invoke(cli.app, ["add", "今天在图书馆坐了一下午"])
    assert 结果.exit_code == 0, 结果.output
    assert "life retry" in 结果.output

    待抽取 = list((临时工作区 / "vault" / "inbox").glob("*.json"))
    assert len(待抽取) == 1, "抽取失败时必须留在 inbox，不能丢"


def test_没配模型时给出能照着做的提示(临时工作区):
    结果 = 运行.invoke(cli.app, ["add", "这条没有 providers.yaml"])
    assert 结果.exit_code == 1
    assert "--demo" in 结果.output
    assert "providers.yaml" in 结果.output


def test_reindex报出扫描结果(临时工作区):
    运行.invoke(cli.app, ["add", "今天读完了两章 Docker 文档", "--demo"])
    结果 = 运行.invoke(cli.app, ["reindex"])
    assert 结果.exit_code == 0
    assert "扫描 1 个记录文件" in 结果.output


def test_私密记录标了private(临时工作区):
    结果 = 运行.invoke(cli.app, ["add", "这句只存本地", "--private", "--demo"])
    assert 结果.exit_code == 0

    条目 = store.读条目(_条目文件(临时工作区)[0])
    assert 条目["private"] is True


def test_一段话讲两件事会拆成两个文件(临时工作区, monkeypatch):
    """§5.2 第 3 条：一条只讲一件事。拆出来的两条不能写进同一个文件。"""
    两条 = {
        "entries": [
            {
                "did": "绕过爬虫反爬：随机 UA + 代理池生效",
                "body": "绕过爬虫反爬，方案为随机 UA 加代理池",
                "part": "record",
                "minutes": 0,
                "outcome": "done",
                "anchors": {"tech": ["随机 UA", "代理池"], "people": [], "link": ""},
                "emotion": {"valence": 0, "arousal": 0, "trigger": "", "quote": ""},
                "level": 2,
                "goal": "",
                "blockers": [],
            },
            {
                "did": "学 Docker，看完两章文档，未动手",
                "body": "开始学 Docker，看了两章官方文档",
                "part": "record",
                "minutes": 0,
                "outcome": "done",
                "anchors": {"tech": ["Docker"], "people": [], "link": ""},
                "emotion": {"valence": 0, "arousal": 0, "trigger": "", "quote": ""},
                "level": 0,
                "goal": "",
                "blockers": [],
            },
        ]
    }

    import json

    monkeypatch.setattr(
        llm,
        "调用",
        lambda *a, **k: llm.模型回复(
            文本=json.dumps(两条, ensure_ascii=False),
            输入token=1,
            输出token=1,
            模型名="测试",
            降级到第几级=1,
        ),
    )
    monkeypatch.setattr(cli.config, "读取任务", lambda 任务名: object())

    结果 = 运行.invoke(cli.app, ["add", "今天绕过反爬，晚上学 Docker"])
    assert 结果.exit_code == 0, 结果.output

    文件们 = _条目文件(临时工作区)
    assert len(文件们) == 2
    assert 文件们[0].stem != 文件们[1].stem
