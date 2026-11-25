"""llm.py —— 唯一和模型打交道的地方。

只用标准库 urllib 发请求，不额外装 HTTP 库（依赖越少，你装环境时越不容易卡住）。

DESIGN.md §4.2 要求结构化输出必须「三级降级」，不允许「请输出 JSON 然后祈祷解析成功」：

  第 1 级  json_schema —— 直接把字段结构交给接口，让它照着结构吐
  第 2 级  json_object —— 接口不支持 schema 时，只要求「返回一个 JSON 对象」
  第 3 级  纯文本      —— 连这个都不支持，就用普通对话，再从回复里抠出 JSON

哪一级成功就用哪一级。三级都失败才报错。
"""

from __future__ import annotations

import base64
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from life import config


class 模型错误(Exception):
    """所有模型相关问题的共同父类。"""


class 网络错误(模型错误):
    """连不上、超时、断网。断网时用户的记录还在硬盘上，所以这个错不致命。"""


class 接口不支持(模型错误):
    """接口不认 response_format，需要降一级再试。"""


@dataclass
class 模型回复:
    """模型回给我们的一段文本，加上账单信息。"""

    文本: str
    输入token: int
    输出token: int
    模型名: str
    降级到第几级: int  # 1=json_schema 2=json_object 3=纯文本


def 调用(
    任务名: str,
    系统提示: str,
    用户内容: str,
    结构: dict | None = None,
    图片路径: Path | None = None,
) -> 模型回复:
    """调一次模型，把回复原文交回去。

    参数里的「结构」是给第 1 级降级用的 JSON Schema；不给就跳过第 1 级。
    """
    任务 = config.读取任务(任务名)
    if 任务 is None:
        raise 配置错误_说明()

    密钥 = 任务.取密钥()
    消息 = _组装消息(系统提示, 用户内容, 图片路径)

    # 从最高的要求往下试
    尝试顺序 = [1, 2, 3] if 结构 else [2, 3]
    最后错误: Exception | None = None

    for 级别 in 尝试顺序:
        try:
            return _发一次(任务, 密钥, 消息, 级别, 结构)
        except 接口不支持 as 错误:
            最后错误 = 错误
            continue

    raise 模型错误(
        f"这个接口三种结构化输出方式都不支持，我没法保证拿到规范的结果。\n"
        f"最后一次的错误是：{最后错误}\n"
        f"建议：把 providers.yaml 里 tasks.{任务名} 换成支持 JSON 输出的模型。"
    )


def _组装消息(系统提示: str, 用户内容: str, 图片路径: Path | None) -> list[dict]:
    """拼消息。纯文字时用户内容就是一段话；有图片时要把图变成 base64 塞进去。"""
    if 图片路径 is None:
        return [
            {"role": "system", "content": 系统提示},
            {"role": "user", "content": 用户内容},
        ]

    后缀 = 图片路径.suffix.lower().lstrip(".") or "png"
    类型 = {"jpg": "jpeg"}.get(后缀, 后缀)
    编码 = base64.b64encode(图片路径.read_bytes()).decode("ascii")
    return [
        {"role": "system", "content": 系统提示},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": 用户内容 or "请看这张图。"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/{类型};base64,{编码}"},
                },
            ],
        },
    ]


def _发一次(
    任务: config.任务配置,
    密钥: str,
    消息: list[dict],
    级别: int,
   结构: dict | None,
) -> 模型回复:
    """按指定级别发一次请求。"""
    请求体: dict = {
        "model": 任务.model,
        "messages": 消息,
        "temperature": 0.2,  # 抽取要稳定，不要文采
        "max_tokens": 2000,
    }

    if 级别 == 1 and 结构:
        请求体["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "抽取结果", "schema": 结构, "strict": True},
        }
    elif 级别 == 2:
        请求体["response_format"] = {"type": "json_object"}
    # 级别 3 什么都不加，就是普通对话

    # ── 发请求 ──
    地址 = f"{任务.base_url}/chat/completions"
    请求 = urllib.request.Request(
        地址,
        data=json.dumps(请求体, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {密钥}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(请求, timeout=60) as 响应:
            原始 = 响应.read().decode("utf-8")
    except urllib.error.HTTPError as 错误:
        详情 = 错误.read().decode("utf-8", errors="replace")
        是不是格式问题 = 错误.code == 400 and any(
            词 in 详情.lower() for 词 in ("response_format", "json_schema", "json_object")
        )
        if 是不是格式问题 and 级别 < 3:
            raise 接口不支持(f"接口不认第 {级别} 级的输出格式：{详情[:200]}") from 错误
        raise 模型错误(
            f"模型接口返回了错误（HTTP {错误.code}）。\n"
            f"接口原话：{详情[:500]}"
        ) from 错误
    except (urllib.error.URLError, socket.timeout, TimeoutError) as 错误:
        raise 网络错误(
            f"连不上模型接口（{任务.base_url}）。\n"
            f"可能是断网、也可能是地址写错了。你的输入已经存在硬盘上，联网后跑 `life retry` 就能补上。\n"
            f"系统原话：{错误}"
        ) from 错误
    except OSError as 错误:
        raise 网络错误(f"发请求时出了系统层面的问题：{错误}") from 错误

    # ── 拆回复 ──
    try:
        数据 = json.loads(原始)
        文本 = 数据["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as 错误:
        raise 模型错误(
            f"接口返回的东西看不懂（不是标准的 chat 格式）。前 300 个字：{原始[:300]}"
        ) from 错误

    用量 = 数据.get("usage") or {}
    return 模型回复(
        文本=文本 or "",
        输入token=int(用量.get("prompt_tokens") or 0),
        输出token=int(用量.get("completion_tokens") or 0),
        模型名=str(数据.get("model") or 任务.model),
        降级到第几级=级别,
    )


def 配置错误_说明() -> config.配置错误:
    """providers.yaml 没配好时，给一段能照着做的说明。"""
    return config.配置错误(
        "还没有配置模型接口，所以没法抽取。\n"
        "\n"
        "两个办法：\n"
        "  1. 想先看看流程能跑通：在命令后面加 --demo，用假模型演示，不联网不花钱。\n"
        "  2. 想真的用 AI：\n"
        "     a. 把 providers.example.yaml 复制成 providers.yaml\n"
        "     b. 把 .env.example 复制成 .env，填上 CHAT_API_KEY=你的密钥\n"
        "     c. 关掉终端重新开一个，让环境变量生效\n"
        "\n"
        f"你说的文件应该在这些位置：\n"
        f"  {config.providers配置文件()}\n"
        f"  {config.工作区根目录() / '.env'}"
    )
