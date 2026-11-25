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
from dataclasses import dataclass, replace
from pathlib import Path

from life import config


def _缩短(文本: str, 上限: int = 300) -> str:
    """上游报错经常是一大坨嵌套 JSON。尽量挑出里面的人话（msg / message）。"""
    import json as _json

    try:
        数据 = _json.loads(文本)
    except (ValueError, TypeError):
        数据 = None

    人话 = ""
    if isinstance(数据, dict):
        for 键 in ("error", "message"):
            值 = 数据.get(键)
            if isinstance(值, dict):
                人话 = str(值.get("msg") or 值.get("message") or "")
            elif isinstance(值, str):
                人话 = 值
            if 人话:
                break

    一行 = " ".join((人话 or 文本).split())
    return 一行 if len(一行) <= 上限 else 一行[:上限] + "…"


class 模型错误(Exception):
    """所有模型相关问题的共同父类。"""


class 网络错误(模型错误):
    """连不上、超时、断网。断网时用户的记录还在硬盘上，所以这个错不致命。"""


class 接口不支持(模型错误):
    """接口不认 response_format，需要降一级再试。"""


class 预算不足(模型错误):
    """思考型模型把 max_tokens 全花在推理上，正文一个字都没剩。

    这种情况值得自动重试——翻倍给额度通常就好了，不该让用户去改配置。
    """


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
    要JSON: bool = True,
) -> 模型回复:
    """调一次模型，把回复原文交回去。

    参数里的「结构」是给第 1 级降级用的 JSON Schema；不给就跳过第 1 级。

    `要JSON=False` 表示这次要的是**人话**（画像、回顾那种散文），
    不要加 response_format——否则模型会硬憋一个 JSON 出来，写进文件就是一片空白。
    """
    任务 = config.读取任务(任务名)
    if 任务 is None:
        raise 配置错误_说明()

    密钥 = 任务.取密钥()
    消息 = _组装消息(系统提示, 用户内容, 图片路径)

    # 从最高的要求往下试
    if 结构:
        尝试顺序 = [1, 2, 3]
    elif 要JSON:
        尝试顺序 = [2, 3]
    else:
        尝试顺序 = [3]
    最后错误: Exception | None = None

    for 级别 in 尝试顺序:
        try:
            return _发一次(任务, 密钥, 消息, 级别, 结构)
        except 预算不足 as 错误:
            # 自动把额度翻倍再试一次（上限 20000），省得用户去改 providers.yaml
            加大 = min(任务.max_tokens * 3, 20000)
            if 加大 <= 任务.max_tokens:
                raise
            try:
                return _发一次(replace(任务, max_tokens=加大), 密钥, 消息, 级别, 结构)
            except 预算不足:
                raise 错误 from None
        except 接口不支持 as 错误:
            最后错误 = 错误
            continue

    raise 模型错误(
        f"这个接口试了三种输出方式都被拒了，我没法保证拿到规范的结果。\n"
        f"最后一次的错误是：{最后错误}\n"
        f"你可以：① 把 providers.yaml 里 tasks.{任务名} 换个模型；"
        f"② 把这段内容拆短一点再记；③ 先不管，内容已经存好了，之后跑 `life retry`。"
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
        "max_tokens": 任务.max_tokens,
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
        with urllib.request.urlopen(请求, timeout=任务.timeout) as 响应:
            原始 = 响应.read().decode("utf-8")
    except urllib.error.HTTPError as 错误:
        详情 = 错误.read().decode("utf-8", errors="replace")

        # 400 / 422 都是「这次请求被拒」。**原因可能藏在很深的 upstream 报错里**
        # （比如网关把上游的 {"code":11135} 包了一层，看不出跟 response_format 有关）。
        # 三级降级的意义就是「不知道原因也往下试」——所以只要还有更低的级别，先降级再说。
        # 实测：上游 400 时第一级 json_schema 被拒，降到第二级就成功了。
        if 错误.code in (400, 422):
            raise 接口不支持(
                f"第 {级别} 级请求被拒（HTTP {错误.code}）：{_缩短(详情)}"
            ) from 错误

        raise 模型错误(
            f"模型接口返回了错误（HTTP {错误.code}）。\n"
            f"接口原话：{_缩短(详情)}\n"
            f"这件事不影响你已经写下的内容——它已经存在硬盘上，"
            f"联网或换模型后跑 `life retry` 就能补。"
        ) from 错误
    except (urllib.error.URLError, socket.timeout, TimeoutError) as 错误:
        是超时 = "timed out" in str(错误).lower() or isinstance(错误, (socket.timeout, TimeoutError))
        if 是超时:
            raise 网络错误(
                f"等了 {任务.timeout} 秒还没返回，我先放弃了（模型 {任务.model} 太慢）。\n"
                f"长文本 + 会思考的模型确实会这样。两个办法：\n"
                f"  1. 把 providers.yaml 里这个任务的 timeout 调大（比如 300）\n"
                f"  2. 把内容拆短一点再记\n"
                f"你的输入已经存在硬盘上，跑 `life retry` 就能补。"
            ) from 错误
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
        选择 = 数据["choices"][0]
        文本 = 选择["message"]["content"] or ""
        结束原因 = 选择.get("finish_reason")
        思考 = 选择["message"].get("reasoning_content") or ""
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as 错误:
        raise 模型错误(
            f"接口返回的东西看不懂（不是标准的 chat 格式）。前 300 个字：{原始[:300]}"
        ) from 错误

    # 思考型模型的坑：token 全花在「想」上，正文一个字都没剩。
    # 这种情况必须说人话，否则用户只会看到一个空文件。
    if not 文本.strip() and 结束原因 == "length":
        raise 预算不足(
            f"模型 {任务.model} 把 {任务.max_tokens} 个 token 全用在「思考」上了，"
            f"正文一个字都没剩下（这次想了 {len(思考)} 字）。\n"
            f"两个办法：\n"
            f"  1. 把 providers.yaml 里这个任务的 max_tokens 调大（比如 8000）\n"
            f"  2. 换一个不思考的模型"
        )

    用量 = 数据.get("usage") or {}
    return 模型回复(
        文本=文本,
        输入token=int(用量.get("prompt_tokens") or 0),
        输出token=int(用量.get("completion_tokens") or 0),
        模型名=str(数据.get("model") or 任务.model),
        降级到第几级=级别,
    )


def 配置错误_说明() -> config.配置错误:
    """providers.yaml 没配好时，给一段能照着做的说明。"""
    return config.配置错误(
        "还没有配置模型接口，所以现在没法调 AI。\n"
        "\n"
        "两个办法：\n"
        "  1. 想先看看流程能跑通：在命令后面加 --demo，用假模型演示，不联网不花钱。\n"
        "  2. 想真的用 AI：\n"
        "     a. 把 providers.example.yaml 复制成 providers.yaml\n"
        "     b. 把 .env.example 复制成 .env，填上 CHAT_API_KEY=你的密钥\n"
        "     c. 关掉终端重新开一个，让环境变量生效\n"
        "\n"
        f"该放的文件位置：\n"
        f"  {config.providers配置文件()}\n"
        f"  {config.工作区根目录() / '.env'}"
    )


# ── 向量（§4.3 第一路检索要用）─────────────────────────────────


def 能向量() -> tuple[bool, str]:
    """能不能做向量检索。返回（能不能，不能的原因）。

    这个函数不抛异常——因为「没有向量接口」是允许的状态：
    检索会自动降级成两路，而不是整个 `life ask` 罢工。
    """
    try:
        任务 = config.读取任务("embed")
    except config.配置错误 as 错误:
        return False, str(错误)

    if 任务 is None:
        return False, "providers.yaml 里没有配置 tasks.embed（向量接口）"
    if not 任务.base_url:
        return False, "tasks.embed 指向的 provider 没写 base_url"
    try:
        任务.取密钥()
    except config.配置错误:
        return False, f"向量接口的密钥没配（.env 里的 {任务.api_key_env} 是空的）"
    return True, ""


def 嵌入(文本们: list[str]) -> tuple[list[list[float]], int]:
    """把一批文本变成向量。返回（向量列表，消耗的 token）。

    接口用的是 OpenAI 兼容的 /embeddings：
        POST {"model": "...", "input": ["...", "..."]}
        →    {"data": [{"index": 0, "embedding": [...]}, ...], "usage": {...}}
    """
    任务 = config.读取任务("embed")
    if 任务 is None:
        raise 配置错误_向量()
    密钥 = 任务.取密钥()

    全部向量: list[list[float]] = []
    总token = 0
    批量 = max(1, min(int(任务.batch or 8), 64))  # 一次最多 64 条，别把接口打挂

    for 起点 in range(0, len(文本们), 批量):
        这一批 = 文本们[起点 : 起点 + 批量]
        原始 = _发嵌入请求(任务, 密钥, 这一批)
        数据 = 原始.get("data") or []
        # 接口不保证按顺序返回，用 index 排一下
        按序 = sorted(数据, key=lambda x: x.get("index", 0))
        全部向量.extend([list(x.get("embedding") or []) for x in 按序])
        用量 = 原始.get("usage") or {}
        总token += int(用量.get("total_tokens") or 用量.get("prompt_tokens") or 0)

    if len(全部向量) != len(文本们):
        raise 模型错误(
            f"向量接口还回来的条数不对：发过去 {len(文本们)} 条，回来 {len(全部向量)} 条。"
        )
    return 全部向量, 总token


def _发嵌入请求(任务: config.任务配置, 密钥: str, 这一批: list[str]) -> dict:
    地址 = f"{任务.base_url}/embeddings"
    请求 = urllib.request.Request(
        地址,
        data=json.dumps({"model": 任务.model, "input": 这一批}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {密钥}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(请求, timeout=任务.timeout) as 响应:
            原始 = 响应.read().decode("utf-8")
    except urllib.error.HTTPError as 错误:
        详情 = 错误.read().decode("utf-8", errors="replace")
        raise 模型错误(
            f"向量接口返回错误（HTTP {错误.code}）。\n接口原话：{详情[:400]}"
        ) from 错误
    except (urllib.error.URLError, socket.timeout, TimeoutError) as 错误:
        raise 网络错误(f"连不上向量接口（{任务.base_url}）：{错误}") from 错误

    try:
        return json.loads(原始)
    except json.JSONDecodeError as 错误:
        raise 模型错误(
            f"向量接口返回的不是 JSON。前 200 个字：{原始[:200]}"
        ) from 错误


def 配置错误_向量() -> config.配置错误:
    return config.配置错误(
        "没有配置向量接口，所以没法做「按意思搜」。\n"
        "\n"
        "两个办法：\n"
        "  1. 先按两路走（全文 + 结构）：生命令时不加 --vectors，检索会自动降级。\n"
        "  2. 想用三路：在 providers.yaml 的 tasks.embed 里配一个支持 /embeddings 的接口\n"
        "     （比如硅基流动的 BAAI/bge-m3），把 key 放进 .env 的 VEC_API_KEY。"
    )
