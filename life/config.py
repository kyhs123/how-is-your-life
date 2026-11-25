"""配置：找到工作区、读 providers.yaml、取出某个任务该用哪个模型。

对应设计文档 DESIGN.md §6.2。这里不写死任何模型名——模型名一律从 providers.yaml 读，
因为不同人的接口和模型不一样。

刻意只做三件事，不搞配置类、不搞单例，因为第 1 周用不上。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

# life/ 这个包所在的目录
包目录 = Path(__file__).resolve().parent


class 配置错误(Exception):
    """配置有问题时抛这个。报错话术直接给用户看，所以写成人话。"""


def 工作区根目录() -> Path:
    """工作区的根目录（vault/、docs/、life/ 都在它下面）。

    正常情况 = life/ 包所在的目录的上一级。
    测试时用环境变量 LIFE_HOME 指到临时目录，这样不会碰你真正的 vault。
    """
    覆盖 = os.environ.get("LIFE_HOME")
    if 覆盖:
        return Path(覆盖).resolve()
    return 包目录.parent


def vault目录() -> Path:
    """用户数据目录。DESIGN.md §3.5：所有记录都在这里。"""
    return 工作区根目录() / "vault"


def providers配置文件() -> Path:
    """providers.yaml 的路径。它不进仓库（里面是你自己的接口地址）。"""
    return 工作区根目录() / "providers.yaml"


@dataclass
class 任务配置:
    """一个任务（比如「抽取」）要用的模型信息。"""

    base_url: str
    api_key_env: str  # 环境变量的名字，不是 key 本身
    model: str
    json模式: str | None = None
    batch: int = 1

    def 取密钥(self) -> str:
        """取真实 key：先看环境变量，再看 .env 文件。

        （Python 不会自动读 .env，所以这里自己读一下，省得你非得去设置系统环境变量。）
        """
        密钥 = os.environ.get(self.api_key_env, "").strip() or _读env文件().get(
            self.api_key_env, ""
        ).strip()
        if not 密钥:
            raise 配置错误(
                f"没有找到环境变量 {self.api_key_env}。\n"
                f"请先在 .env 里写上 {self.api_key_env}=你的密钥，"
                f"再重新打开一个终端窗口，或者先加 --demo 用假模型跑。"
            )
        return 密钥


def 读取任务(任务名: str) -> 任务配置 | None:
    """读 providers.yaml 里 tasks.<任务名> 这一段。

    文件不存在、或者这一段没配 → 返回 None（调用方决定怎么办）。
    """
    路径 = providers配置文件()
    if not 路径.exists():
        return None

    try:
        全部 = yaml.safe_load(路径.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as 错误:
        raise 配置错误(f"providers.yaml 格式写错了，读不出来：{错误}") from 错误

    任务表 = (全部.get("tasks") or {}).get(任务名)
    if not 任务表:
        return None

    厂商表 = (全部.get("providers") or {}).get(任务表.get("provider"))
    if not 厂商表:
        raise 配置错误(
            f"providers.yaml 里 tasks.{任务名} 指向的 provider「{任务表.get('provider')}」"
            f"没有定义。请检查 providers 那一段。"
        )

    return 任务配置(
        base_url=str(厂商表.get("base_url", "")).rstrip("/"),
        api_key_env=str(厂商表.get("api_key_env", "")),
        model=str(任务表.get("model", "")),
        json模式=任务表.get("json"),
        batch=int(任务表.get("batch", 1)),
    )


def env文件路径() -> Path:
    """本地的 .env（填密钥用，不进仓库）。"""
    return 工作区根目录() / ".env"


def _读env文件() -> dict[str, str]:
    """把 .env 读成一个字典。

    只认 `名字=值` 这一种写法，跳过空行和 # 开头的注释行。
    不引第三方库，因为就这几行逻辑。
    """
    路径 = env文件路径()
    if not 路径.exists():
        return {}

    结果: dict[str, str] = {}
    for 原行 in 路径.read_text(encoding="utf-8").splitlines():
        行 = 原行.strip()
        if not 行 or 行.startswith("#") or "=" not in 行:
            continue
        名字, 值 = 行.split("=", 1)
        结果[名字.strip()] = 值.strip().strip('"').strip("'")
    return 结果


def prompt文件(文件名: str) -> Path:
    """prompt 放在 life/prompts/ 里，是纯文本，改它不用动 Python 代码。

    DESIGN.md §4.2：禁止把 prompt 硬编码在代码里。
    """
    路径 = 包目录 / "prompts" / 文件名
    if not 路径.exists():
        raise 配置错误(f"找不到 prompt 文件：{路径}")
    return 路径
