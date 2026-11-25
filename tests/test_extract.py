"""测 extract.py：解析、校验、重试降级、private 不外发。"""

from __future__ import annotations

import json

import pytest

from life import extract, fake_model, llm


def test_整段就是JSON能解析():
    数据, 错误 = extract._解析('{"entries":[]}')
    assert 错误 == ""
    assert 数据 == {"entries": []}


def test_包在代码块里也能解析():
    """第 3 级降级要处理的正是这种情况。"""
    文本 = '好的，结果如下：\n```json\n{"entries": [{"did": "接通 OAuth"}]}\n```\n'
    数据, 错误 = extract._解析(文本)
    assert 错误 == ""
    assert 数据["entries"][0]["did"] == "接通 OAuth"


def test_前后有废话也能抠出来():
    文本 = '这是结果 {"entries": [{"did": "接通 OAuth"}]} 希望有用'
    数据, 错误 = extract._解析(文本)
    assert 错误 == ""
    assert 数据["entries"][0]["did"] == "接通 OAuth"


def test_完全不是JSON就返回错误():
    数据, 错误 = extract._解析("我觉得你今天挺棒的")
    assert 数据 is None
    assert "找不到能解析的 JSON" in 错误


def test_did超过60字要报错():
    候选 = {"did": "啊" * 61, "part": "record", "anchors": {"tech": ["X"]}}
    错误 = extract.校验条目(候选)
    assert any("超过 60 字" in 一条 for 一条 in 错误)


def test_record没有锚点要报错():
    候选 = {"did": "今天做了某事", "part": "record", "anchors": {}}
    错误 = extract.校验条目(候选)
    assert any("一个锚点都没有" in 一条 for 一条 in 错误)


def test_情感记录没有锚点不算错():
    """「今天很累」这种本来就没有技术锚点，不该拦。"""
    候选 = {"did": "今天很累，什么都不想做", "part": "emotion", "anchors": {}}
    assert extract.校验条目(候选) == []


def test_假模型对设计文档里的例子给出的结果能通过校验():
    """DESIGN.md §5.3 那段原话，假模型也得产出「能用」的东西。"""
    原话 = (
        "今天又在搞那个 oauth 的登录，烦死了，文档写得跟屎一样，"
        "试了半天发现 state 参数要签名，弄完已经一点多了，不过总算跑通了，明天还得接前端"
    )
    结果 = fake_model.假抽取(原话)
    assert extract.校验全部(结果) == []
    assert 结果["entries"][0]["minutes"] == 0 or 结果["entries"][0]["minutes"] > 0


def test_模型两次都给垃圾就标needs_review(临时工作区, monkeypatch):
    """§4.2：两次失败标 needs_review，不静默丢弃。"""
    调用次数 = []

    def 假调用(*args, **kwargs):
        调用次数.append(1)
        return llm.模型回复(文本="我不会做这个", 输入token=1, 输出token=1, 模型名="测试", 降级到第几级=3)

    monkeypatch.setattr(llm, "调用", 假调用)
    # 让 config 以为配置过了，否则会先报配置错误
    monkeypatch.setattr(extract.config, "读取任务", lambda 任务名: object())

    结果 = extract.抽取("今天把 OAuth 调通了")
    assert len(调用次数) == 2, "应该重试一次，总共调两次"
    assert 结果["status"] == "needs_review"
    assert 结果["entries"][0]["did"], "兜底也要留下原话，不能是空"


def test_private完全不调用模型(临时工作区, monkeypatch):
    """§8：private 的记录不进任何 API 调用。"""

    def 不许调用(*args, **kwargs):
        raise AssertionError("private 的记录不该调用模型")

    monkeypatch.setattr(llm, "调用", 不许调用)

    结果 = extract.抽取("这句只存本地", 私密=True)
    assert 结果["status"] == "needs_review"
    assert 结果["entries"][0]["did"] == "这句只存本地"


def test_prompt版本随内容变化(临时工作区):
    """prompt 一改，缓存键就变，不会拿旧结果糊弄人。"""
    版本 = extract.prompt版本("extract.md")
    assert len(版本) == 8
    assert extract.prompt版本("extract_image.md") != 版本


def test_缓存按prompt版本和模型分开存(临时工作区):
    """§4.2 缓存键 = (内容指纹, prompt 版本, 模型)。换哪一个都该重抽。"""
    结果 = {
        "entries": [],
        "ocr_text": "",
        "digest": "",
        "status": "settled",
        "备注": "",
        "prompt_ver": "abcd1234",
        "模型名": "假模型",
    }
    extract.写缓存("abc123", 结果, [])

    缓存 = extract.读缓存("abc123")
    assert extract.取缓存结果(缓存, "abcd1234", "假模型")["status"] == "settled"
    assert extract.取缓存结果(缓存, "abcd1234", "别的模型") is None
    assert extract.取缓存结果(缓存, "换了版本", "假模型") is None


def test_缓存记下了指纹对应的记录文件(临时工作区):
    """下次重复提交时靠它判断「这条已经记过了」。"""
    from life import store

    条目 = store.新建条目(
        id="20261125-143200",
        ts="2026-11-25T14:32:00+08:00",
        did="接通 OAuth，锚点 OAuth",
        body="接通 OAuth，锚点 OAuth",
        anchors={"tech": ["OAuth"], "people": [], "link": ""},
        level=2,
    )
    路径 = store.写条目(条目)
    extract.写缓存("abc123", {"entries": [], "prompt_ver": "abcd1234", "模型名": "假模型"}, [路径])

    assert extract.读缓存("abc123")["entry_paths"] == ["now/2026-11/20261125-143200.md"]


def test_模型返回空列表时原话必须留下(临时工作区, monkeypatch):
    """真模型实测踩到的坑：它说「没什么可记的」，返回空列表。

    如果照单全收，用户写的那句话就静默消失了。这里要求兜底保存。
    """

    class 假任务配置:
        model = "测试模型"

    monkeypatch.setattr(
        llm,
        "调用",
        lambda *a, **k: llm.模型回复(
            文本='{"entries": []}', 输入token=1, 输出token=1, 模型名="测试模型", 降级到第几级=1
        ),
    )
    monkeypatch.setattr(extract.config, "读取任务", lambda 任务名: 假任务配置())

    结果 = extract.抽取("今天做了某事")
    assert 结果["status"] == "needs_review"
    assert 结果["entries"], "模型说没什么可记的，但原话必须存下来"
    assert 结果["entries"][0]["did"] == "今天做了某事"


def test_空输入不调用模型(临时工作区, monkeypatch):
    """真模型被喂空字符串会编一条出来（实测编过网络配置），所以这里直接拦住。"""

    def 不许调用(*args, **kwargs):
        raise AssertionError("空输入不该调用模型")

    monkeypatch.setattr(llm, "调用", 不许调用)

    结果 = extract.抽取("   ")
    assert 结果["entries"] == []
    assert 结果["status"] == "needs_review"
    assert "空的" in 结果["备注"]


def test_坏掉的缓存不影响使用(临时工作区):
    extract.写缓存("坏掉", {"entries": [], "prompt_ver": "x", "模型名": "y"}, [])
    (extract.缓存目录() / "坏掉.json").write_text("{这不是 json", encoding="utf-8")
    assert extract.读缓存("坏掉") is None


def test_同样的内容不会被抽两次(临时工作区, monkeypatch):
    """§4.2 缓存：内容 + prompt + 模型都一样，第二次应该直接拿缓存。"""
    import json

    from life import llm

    次数 = []

    def 假调用(*args, **kwargs):
        次数.append(1)
        return llm.模型回复(
            文本=json.dumps(
                {
                    "entries": [
                        {
                            "did": "接通 OAuth，卡点 state 签名",
                            "body": "接通 OAuth，卡点 state 签名",
                            "part": "record",
                            "minutes": 0,
                            "outcome": "done",
                            "anchors": {"tech": ["OAuth"], "people": [], "link": ""},
                            "emotion": {
                                "valence": 0,
                                "arousal": 0,
                                "trigger": "",
                                "quote": "",
                            },
                            "level": 2,
                            "goal": "",
                            "blockers": [],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            输入token=1,
            输出token=1,
            模型名="测试模型",
            降级到第几级=1,
        )

    class 假任务配置:
        model = "测试模型"

    monkeypatch.setattr(llm, "调用", 假调用)
    monkeypatch.setattr(extract.config, "读取任务", lambda 任务名: 假任务配置())

    第一次 = extract.抽取("接通 OAuth，卡点 state 签名", 内容指纹="同一个指纹")
    extract.写缓存("同一个指纹", 第一次, [])
    第二次 = extract.抽取("接通 OAuth，卡点 state 签名", 内容指纹="同一个指纹")

    assert len(次数) == 1, "第二次应该命中缓存，不该再调一次模型"
    assert 第二次.get("命中缓存") is True
    assert 第二次["entries"][0]["did"] == 第一次["entries"][0]["did"]
