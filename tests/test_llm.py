"""测模型网关——三级降级（只在网络上打桩，断言看最终结果）。

为什么这里要打桩：真调接口要联网、要花钱、还会因为上游抽风而红。
但被测的行为是用户能感知的：「接口不认第一级格式时，记录还能不能抽出来」。
"""

from __future__ import annotations

import io
import json
import urllib.error
from dataclasses import dataclass

import pytest

from life import llm


class 假响应:
    def __init__(self, 数据: bytes):
        self.数据 = 数据

    def read(self) -> bytes:
        return self.数据

    def __enter__(self):
        return self

    def __exit__(self, *参数):
        return False


@dataclass
class 假任务:
    """要真正的 dataclass —— 加预算那一支会用 dataclasses.replace() 复制它。"""

    base_url: str = "http://127.0.0.1:1/v1"
    api_key_env: str = "X"
    model: str = "测试模型"
    max_tokens: int = 100
    timeout: int = 5
    batch: int = 1
    json模式: str | None = None

    def 取密钥(self) -> str:
        return "假密钥"


def _成功回复(内容: str) -> 假响应:
    return 假响应(
        json.dumps(
            {
                "choices": [{"message": {"content": 内容}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                "model": "测试模型",
            },
            ensure_ascii=False,
        ).encode("utf-8")
    )


def _四百(说明: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://127.0.0.1:1/v1/chat/completions",
        400,
        "Bad Request",
        {},
        io.BytesIO(json.dumps({"error": {"message": 说明}}, ensure_ascii=False).encode()),
    )


def test_第一级被拒会自动降级并成功(临时工作区, monkeypatch):
    """上游 400 的报错常常看不出跟 response_format 有关（网关会包一层）。

    真实遇到的情况：`upstream 400 ... {"code":11135}`。
    三级降级的意义就是「不知道原因也往下试」，所以这种 400 必须再试一级。
    """
    次数 = {"n": 0}

    def 假urlopen(请求, timeout=None):
        次数["n"] += 1
        if 次数["n"] == 1:
            raise _四百('upstream 400: {"code":11135}')
        return _成功回复('{"entries":[]}')

    monkeypatch.setattr(llm.urllib.request, "urlopen", 假urlopen)
    monkeypatch.setattr(llm.config, "读取任务", lambda 名: 假任务())

    回复 = llm.调用("extract", "系统提示", "用户内容", 结构={"type": "object"})

    assert 次数["n"] == 2, "应该降一级再试，而不是直接放弃"
    assert 回复.降级到第几级 == 2
    assert "entries" in 回复.文本


def test_三级都被拒时报错说清楚且不吓人(临时工作区, monkeypatch):
    def 假urlopen(请求, timeout=None):
        raise _四百('upstream 400: {"code":11135}')

    monkeypatch.setattr(llm.urllib.request, "urlopen", 假urlopen)
    monkeypatch.setattr(llm.config, "读取任务", lambda 名: 假任务())

    with pytest.raises(llm.模型错误) as 捕获:
        llm.调用("extract", "系统提示", "用户内容", 结构={"type": "object"})

    消息 = str(捕获.value)
    assert "三种输出方式" in 消息, 消息
    assert "life retry" in 消息, "要告诉用户内容没丢、怎么补救"
    assert "11135" in 消息


def test_思考型模型把token用光时给看得懂的话(临时工作区, monkeypatch):
    """正文为空 + finish_reason=length = 额度全花在思考上，不能写个空文件了事。"""
    def 假urlopen(请求, timeout=None):
        return 假响应(
            json.dumps(
                {
                    "choices": [
                        {"message": {"content": "", "reasoning_content": "想了很久"}, "finish_reason": "length"}
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 100},
                    "model": "测试模型",
                },
                ensure_ascii=False,
            ).encode("utf-8")
        )

    monkeypatch.setattr(llm.urllib.request, "urlopen", 假urlopen)
    monkeypatch.setattr(llm.config, "读取任务", lambda 名: 假任务())

    with pytest.raises(llm.模型错误) as 捕获:
        llm.调用("settle", "系统提示", "用户内容", 要JSON=False)

    消息 = str(捕获.value)
    assert "思考" in 消息
    assert "max_tokens" in 消息
