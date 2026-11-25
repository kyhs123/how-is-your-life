"""jobs.py —— 后台任务（docs/WEBUI.md §2.6）。

网页上那些「要跑一两分钟」的活（生成画像、写回顾、归纳主题），不能同步等——
浏览器会转圈、看着像卡死。所以：

    点按钮 → 起一个后台线程 → 立刻跳到任务页 → 任务页每 3 秒自刷 → 完成显示结果

设计取舍：

- **任务表放内存**：进程一停就没了。这是本机小工具，够用；不引数据库、不引队列。
- **同类只允许一个**：重复点按钮不会叠着跑两遍（画像一次要花不少 token）。
- **不做假进度条**：模型调用没有可靠的进度回调。只显示「已经跑了多少秒」，
  编一个百分比比转圈更糟。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

# 最多留这么多个历史任务，免得内存表无限长
最多保留 = 20


@dataclass
class 任务:
    id: str
    动作: str  # portrait / review / settle / reindex
    名称: str  # 给人看的名字
    状态: str = "running"  # running | done | failed
    开始: float = field(default_factory=time.time)
    结束: float = 0.0
    结果: str = ""
    错误: str = ""
    去向: str = ""  # 完成后建议去哪个页面看

    @property
    def 用了多少秒(self) -> float:
        return (self.结束 or time.time()) - self.开始

    @property
    def 跑完了吗(self) -> bool:
        return self.状态 != "running"


_任务表: dict[str, 任务] = {}
_正在跑: dict[str, str] = {}  # 动作 → 任务 id
_锁 = threading.Lock()


def 启动(动作: str, 名称: str, 函数, *, 去向: str = "") -> tuple[任务, bool]:
    """起一个后台任务。返回（任务，是不是新起的）。

    同类任务已经在跑时返回正在跑的那个（`是不是新起的=False`），不会叠着跑。
    """
    with _锁:
        在跑 = _正在跑.get(动作)
        if 在跑 and 在跑 in _任务表:
            return _任务表[在跑], False

        任务号 = uuid.uuid4().hex[:12]
        新任务 = 任务(id=任务号, 动作=动作, 名称=名称, 去向=去向)
        _任务表[任务号] = 新任务
        _正在跑[动作] = 任务号

    def 跑() -> None:
        try:
            摘要 = 函数()
            新任务.结果 = str(摘要 or "完成")
            新任务.状态 = "done"
        except Exception as 错误:  # noqa: BLE001 —— 后台任务必须自己兜住一切
            新任务.状态 = "failed"
            新任务.错误 = f"{type(错误).__name__}: {错误}"
        finally:
            新任务.结束 = time.time()
            with _锁:
                _正在跑.pop(动作, None)
                _清理()

    threading.Thread(target=跑, daemon=True, name=f"任务-{动作}").start()
    return 新任务, True


def 取(任务号: str) -> 任务 | None:
    return _任务表.get(任务号)


def 列表(最多: int = 10) -> list[任务]:
    return sorted(_任务表.values(), key=lambda t: t.开始, reverse=True)[:最多]


def 正在跑(动作: str) -> 任务 | None:
    任务号 = _正在跑.get(动作)
    return _任务表.get(任务号) if 任务号 else None


def _清理() -> None:
    if len(_任务表) <= 最多保留:
        return
    过期 = sorted(_任务表.values(), key=lambda t: t.开始)[: len(_任务表) - 最多保留]
    for 任务 in 过期:
        if 任务.跑完了:
            _任务表.pop(任务.id, None)
