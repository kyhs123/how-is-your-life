"""recorder.py —— 记一条记录的完整链路。

命令行（`life add`）和本机网页（`life server` 的「记一条」）走的是**同一段代码**，
不是两份实现。这一点很重要：落盘顺序、去重、图片处理只要有两份，早晚会不一致。

顺序（DESIGN.md §4.1 / C5）：

    算指纹 → 查重复 → 写 vault/inbox/<id>.json（★这一行之后内容就不会丢了）
    → 调模型抽取 → 写 vault/now/<月>/<id>.md → 建索引 → 删 inbox → 写缓存

抽取失败不影响「已经记下来」这件事，inbox 会留着等 `life retry`。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from life import config, extract, index, llm, store

提示函数 = Callable[[str], None]


def _不说(_: str) -> None:
    pass


def 记录一条(
    原文: str,
    *,
    图片: Path | None = None,
    情感: bool = False,
    私密: bool = False,
    保留图片: bool = False,
    用假模型: bool = False,
    提示: 提示函数 | None = None,
) -> dict:
    """记一条。返回结果字典，调用方负责把结果变成屏幕上的一句话。

    返回值：
        {
          "状态": "重复" | "成功" | "抽取失败" | "配置错误" | "输入有问题",
          "路径们": [Path],          # 写出来的记录文件
          "收件": Path | None,        # inbox 里那个 json
          "错误": str,
        }
    """
    说 = 提示 or _不说

    if not 原文.strip() and 图片 is None:
        return {"状态": "输入有问题", "路径们": [], "收件": None, "错误": "什么都没有输入。"}

    if 图片 is not None and not 图片.exists():
        return {
            "状态": "输入有问题",
            "路径们": [],
            "收件": None,
            "错误": f"找不到这张图：{图片}",
        }

    vault = store.确保vault就绪()
    此刻 = store.现在()
    输入id, _ = store.分配id(此刻)

    # ① 图片先复制进 vault（C1：文件必须在仓库内；用户可能马上删掉原图）
    暂存图: Path | None = None
    if 图片 is not None:
        try:
            暂存图 = store.复制图片到暂存(图片, 输入id)
        except OSError as 错误:
            return {
                "状态": "输入有问题",
                "路径们": [],
                "收件": None,
                "错误": f"复制图片失败：{错误}",
            }

    # ② 算指纹，看是不是重复提交（§4.1 幂等）
    指纹 = store.内容哈希(原文, 暂存图)
    已有 = extract.读缓存(指纹)
    if 已有 and any((vault / 相对) .exists() for 相对 in 已有.get("entry_paths", [])):
        if 暂存图 is not None:
            暂存图.unlink(missing_ok=True)
        说("· 这条之前已经记过了，不重复存：")
        for 相对 in 已有.get("entry_paths", []):
            说(f"    vault/{相对}")
        return {"状态": "重复", "路径们": [], "收件": None, "错误": ""}

    # ③ 先落盘（C5）。这一行执行完，这条内容就不会丢了。
    输入 = {
        "格式": 1,
        "id": 输入id,
        "ts": store.时间文本(此刻),
        "kind": "image" if 暂存图 else "text",
        "原文": 原文,
        "部分": "emotion" if 情感 else "record",
        "private": 私密,
        "keep_image": 保留图片,
        "图片": str(暂存图.relative_to(vault)).replace("\\", "/") if 暂存图 else "",
        "图片原名": 图片.name if 图片 else "",
        "内容指纹": 指纹,
        "尝试次数": 0,
        "最后错误": "",
    }
    收件路径 = store.写inbox(输入)
    说(f"· 已存好：vault/inbox/{收件路径.name}")

    # ④ 抽取（失败也不影响上面那条已经存好的记录）
    try:
        路径们, 结果 = 抽取并保存(输入, 用假模型=用假模型, 提示=说)
    except llm.网络错误 as 错误:
        return {"状态": "抽取失败", "路径们": [], "收件": 收件路径, "错误": str(错误)}
    except config.配置错误 as 错误:
        return {"状态": "配置错误", "路径们": [], "收件": 收件路径, "错误": str(错误)}
    except (llm.模型错误, extract.抽取错误, index.索引错误) as 错误:
        return {"状态": "抽取失败", "路径们": [], "收件": 收件路径, "错误": str(错误)}

    # ⑤ 收尾：清掉待抽取文件、处理图片、写缓存
    store.删inbox(收件路径)
    处理图片(输入, vault, 暂存图, 结果, 提示=说)
    extract.写缓存(指纹, 结果, 路径们)

    for 路径 in 路径们:
        说(f"√ 记下了：vault/{str(路径.relative_to(vault)).replace(chr(92), '/')}")

    return {"状态": "成功", "路径们": 路径们, "收件": 收件路径, "错误": ""}


def 抽取并保存(
    输入: dict, *, 用假模型: bool, 图片: Path | None = None, 提示: 提示函数 | None = None
) -> tuple[list[Path], dict]:
    """一次输入 → 抽取 → 写成 markdown → 进索引。返回（文件路径列表，抽取结果）。"""
    说 = 提示 or _不说
    vault = config.vault目录()

    if 图片 is None and 输入.get("图片"):
        可能 = vault / 输入["图片"]
        图片 = 可能 if 可能.exists() else None

    结果 = extract.抽取(
        输入.get("原文", ""),
        部分=输入.get("部分", "record"),
        图片路径=图片,
        原文文件名=输入.get("图片原名", ""),
        私密=bool(输入.get("private")),
        用假模型=用假模型,
        内容指纹=输入.get("内容指纹", ""),
    )

    if 结果["status"] == "needs_review" and 结果.get("备注"):
        说(f"· {结果['备注']}")

    连接 = index.连接索引()
    try:
        from datetime import datetime

        时间 = datetime.fromisoformat(输入["ts"])
        路径们: list[Path] = []
        for 一条 in 结果["entries"]:
            记录id, 时间 = store.分配id(时间)
            条目 = store.新建条目(
                id=记录id,
                ts=store.时间文本(时间),
                private=bool(输入.get("private")),
                status=结果["status"],
                **一条,
            )
            路径 = store.写条目(条目)
            index.写入条目(连接, 条目)
            路径们.append(路径)
        return 路径们, 结果
    finally:
        连接.close()


def 处理图片(
    输入: dict,
    vault: Path,
    暂存图: Path | None,
    结果: dict,
    *,
    提示: 提示函数 | None = None,
) -> None:
    """按设计处理图片：OCR 全文留下，原图删掉（除非用户说了 --keep-image）。"""
    说 = 提示 or _不说
    if 暂存图 is None:
        return

    if 输入.get("kind") == "image":
        正文 = (
            f"# 图片原文（OCR）\n\n"
            f"{结果.get('ocr_text') or '（没有识别出文字）'}\n\n"
            f"# 摘要\n\n{结果.get('digest') or '（没有摘要）'}\n"
        )
        (vault / "media" / f"{输入['id']}.md").write_text(正文, encoding="utf-8")

    if 输入.get("keep_image"):
        目标 = vault / "media" / 暂存图.name
        目标.parent.mkdir(parents=True, exist_ok=True)
        暂存图.replace(目标)
        说(f"· 原图按你的要求留下了：vault/media/{目标.name}")
    else:
        暂存图.unlink(missing_ok=True)
