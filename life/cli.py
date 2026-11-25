"""cli.py —— 命令入口。用户敲的每一条 `life ...` 都从这里开始。

第 1 周只有三个命令：

    life add      录入（先落盘，再抽取）
    life retry    把 vault/inbox/ 里没抽成功的补抽一遍
    life reindex  从 markdown 重建索引

DESIGN.md 里第 1 周没要求别的命令，就不做——多做的东西没人用，还会变成负担。
"""

from __future__ import annotations

import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from life import config, extract, index, llm, retrieve, store
from life import ask as ask模块
from life import board as board模块

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="How Is Your Life「你过得怎么样」——本地人生记录工具。第 1 周：录入 / 抽取 / 索引。",
)


# ── life add ──────────────────────────────────────────────────


@app.command()
def add(
    文本: str = typer.Argument("", help="要说的话，加引号。比如 life add \"今天调通了 OAuth\""),
    图片: Optional[Path] = typer.Option(None, "--image", help="配一张图片（截图、笔记照片）"),
    情感: bool = typer.Option(False, "--emotion", help="这条是感受，不是做了什么"),
    私密: bool = typer.Option(
        False, "--private", help="只存本地，绝不发给任何接口（也不会被以后的检索翻出来）"
    ),
    保留图片: bool = typer.Option(
        False, "--keep-image", help="破例保留原图（设计默认不存原图）"
    ),
    演示: bool = typer.Option(False, "--demo", help="用假模型演示，不联网不花钱"),
):
    """记一件事。先把内容写进硬盘，再想办法压缩成一句话。"""
    if not 文本.strip() and 图片 is None:
        typer.echo('× 你什么都没输入。\n  用法：life add "今天做了什么"\n        life add --image 图片路径 "说明"')
        raise typer.Exit(1)

    if 图片 is not None and not 图片.exists():
        typer.echo(f"× 找不到这张图：{图片}")
        raise typer.Exit(1)

    vault = store.确保vault就绪()
    此刻 = store.现在()
    输入id, _ = store.分配id(此刻)

    # ① 图片先复制进 vault（C1：文件必须在仓库内；用户可能马上删掉原图）
    暂存图: Path | None = None
    if 图片 is not None:
        try:
            暂存图 = store.复制图片到暂存(图片, 输入id)
        except OSError as 错误:
            typer.echo(f"× 复制图片失败：{错误}")
            raise typer.Exit(1) from 错误

    # ② 算指纹，看看是不是重复提交（§4.1 幂等）
    指纹 = store.内容哈希(文本, 暂存图)
    已有 = extract.读缓存(指纹)
    if 已有 and any(
        (vault / 相对路径).exists() for 相对路径 in 已有.get("entry_paths", [])
    ):
        typer.echo("· 这条之前已经记过了，不重复存：")
        for 相对路径 in 已有.get("entry_paths", []):
            typer.echo(f"    vault/{相对路径}")
        if 暂存图 is not None:
            暂存图.unlink(missing_ok=True)
        return

    # ③ 先落盘（C5）。这一行执行完，这条内容就不会丢了。
    输入 = {
        "格式": 1,
        "id": 输入id,
        "ts": store.时间文本(此刻),
        "kind": "image" if 暂存图 else "text",
        "原文": 文本,
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
    typer.echo(f"· 已存好：vault/inbox/{收件路径.name}")

    if 演示:
        typer.echo("· 这次用的是假模型（--demo），不会真的调用 AI。")

    # ④ 抽取（可能失败，失败也不影响上面那条已经存好的记录）
    try:
        路径们, 结果 = _抽取并保存(输入, 用假模型=演示)
    except llm.网络错误 as 错误:
        typer.echo(f"· 抽取没成功（网络问题），但记录已经存好了。\n  {错误}")
        typer.echo("  联网之后跑 `life retry` 就能补上。")
        return
    except config.配置错误 as 错误:
        typer.echo(f"× {错误}")
        typer.echo(f"  你的输入已经存好了：vault/inbox/{收件路径.name}")
        raise typer.Exit(1) from 错误
    except (llm.模型错误, extract.抽取错误, index.索引错误) as 错误:
        typer.echo(f"· 抽取没成功，但记录已经存好了。\n  {错误}")
        typer.echo("  排查完再跑 `life retry` 即可。")
        return

    # ⑤ 收尾：清掉待抽取文件、处理图片、写缓存
    store.删inbox(收件路径)
    _处理图片(输入, vault, 暂存图, 结果)
    extract.写缓存(指纹, 结果, 路径们)

    for 路径 in 路径们:
        typer.echo(f"√ 记下了：vault/{str(路径.relative_to(vault)).replace(chr(92), '/')}")
    typer.echo("  （想看这条长什么样，用记事本打开上面那个文件。）")


# ── life retry ────────────────────────────────────────────────


@app.command()
def retry(演示: bool = typer.Option(False, "--demo", help="用假模型演示，不联网不花钱")):
    """把 vault/inbox/ 里还没抽成功的输入，再抽一遍。"""
    vault = store.确保vault就绪()
    文件们 = store.列出inbox()
    if not 文件们:
        typer.echo("· 待抽取队列是空的，没有要补的。")
        return

    typer.echo(f"· 有 {len(文件们)} 条等着抽取。")
    成功 = 0
    失败 = 0
    for 路径 in 文件们:
        try:
            输入 = store.读inbox(路径)
        except store.存储错误 as 错误:
            typer.echo(f"× {错误}")
            失败 += 1
            continue

        暂存图 = vault / 输入["图片"] if 输入.get("图片") else None
        if 暂存图 is not None and not 暂存图.exists():
            暂存图 = None  # 图片已经被清掉了，按纯文字重试

        try:
            路径们, 结果 = _抽取并保存(输入, 用假模型=演示, 图片=暂存图)
        except (llm.模型错误, extract.抽取错误, index.索引错误, config.配置错误) as 错误:
            typer.echo(f"× {路径.name} 还是不行：{错误}")
            失败 += 1
            continue

        store.删inbox(路径)
        _处理图片(输入, vault, 暂存图, 结果)
        extract.写缓存(输入.get("内容指纹", ""), 结果, 路径们)
        for 一条 in 路径们:
            typer.echo(f"√ 记下了：vault/{str(一条.relative_to(vault)).replace(chr(92), '/')}")
        成功 += 1

    typer.echo(f"· 完成：补抽 {成功} 条，仍失败 {失败} 条。")


# ── life ask ──────────────────────────────────────────────────


@app.command()
def ask(
    问题: str = typer.Argument(..., help="你想问的话，加引号。比如 life ask \"我好累\""),
    取几条: int = typer.Option(6, "--num", help="召回几条旧记录（5~8 最合适）"),
    不用向量: bool = typer.Option(
        False, "--no-vectors", help="跳过向量路，只走全文 + 结构两路"
    ),
    只看召回: bool = typer.Option(
        False, "--dry-run", help="只显示召回到哪几条记录，不调对话模型（省钱、方便排查）"
    ),
):
    """带着你以前的记录回答问题。"""
    if 只看召回:
        _打印召回(问题, 取几条=取几条, 用向量=not 不用向量)
        return

    try:
        结果 = ask模块.问(问题, 取几条=取几条, 用向量=not 不用向量)
    except config.配置错误 as 错误:
        typer.echo(f"× {错误}")
        raise typer.Exit(1) from 错误
    except llm.网络错误 as 错误:
        typer.echo(f"× 连不上模型，这次没回答成。\n  {错误}")
        raise typer.Exit(1) from 错误
    except llm.模型错误 as 错误:
        typer.echo(f"× 模型那边出问题了。\n  {错误}")
        raise typer.Exit(1) from 错误

    typer.echo("")
    typer.echo(结果["回答"].strip())
    typer.echo("")

    if 结果["没做到"]:
        typer.echo("· 这次回答有几条硬要求没做到（已经重试过一次）：")
        for 一条 in 结果["没做到"]:
            typer.echo(f"    - {一条}")
        typer.echo("  （这是模型的问题，不是你写错了。可以再问一次，或者调 prompt。）")

    typer.echo(
        f"· 用到了 {len(结果['召回'])} 条旧记录 ｜ 上下文约 {结果['上下文token']} token "
        f"｜ 本次 {结果['token']} token"
    )
    for 提示 in 结果["诊断"].get("提示", []):
        typer.echo(f"· {提示}")


def _打印召回(问题: str, *, 取几条: int, 用向量: bool) -> None:
    """--dry-run：只给检索结果，让人能判断「它到底有没有翻出该翻出来的东西」。"""
    try:
        结果, 诊断 = retrieve.召回(问题, 取几条=取几条, 用向量=用向量)
    except index.索引错误 as 错误:
        typer.echo(f"× {错误}")
        raise typer.Exit(1) from 错误

    typer.echo(f"· 查询：{问题}")
    各路 = 诊断.get("各路", {})
    typer.echo(
        "· 三路命中："
        + "、".join(f"{名} {数} 条" for 名, 数 in 各路.items())
    )
    走了 = 诊断.get("结构走了哪几条") or []
    if 走了:
        typer.echo(f"· 结构检索走了：{'、'.join(走了)}")
    for 提示 in 诊断.get("提示", []):
        typer.echo(f"· {提示}")

    if not 结果:
        typer.echo("· 一条都没召回到。")
        return

    typer.echo("")
    for 名次, 条目 in enumerate(结果, start=1):
        档 = {0: "接触", 1: "复现", 2: "产出", 3: "能讲"}.get(条目["level"], "?")
        typer.echo(
            f"{名次}. {条目['ts'][:10]}（{档}）{'/'.join(条目['来源'])} ｜ {条目['did']}"
        )


# ── life board ────────────────────────────────────────────────


@app.command()
def board(
    输出: Optional[Path] = typer.Option(
        None, "--out", help="写到哪个文件。默认 vault/看板.html"
    ),
    含私密: bool = typer.Option(
        False, "--include-private", help="连私密记录一起显示（别把这个文件发给别人）"
    ),
    打开: bool = typer.Option(False, "--open", help="生成后用浏览器打开"),
):
    """生成一个单文件网页看板，双击就能看自己的记录。"""
    文件, 统计 = board模块.生成(输出, 含私密=含私密)

    库 = store.确保vault就绪()
    typer.echo(f"√ 看板已生成：{文件}")
    typer.echo(
        f"  {统计['条数']} 条记录 ｜ 证据档："
        + "、".join(
            f"{board模块.档位名称[档]} {统计['档位'].get(档, 0)}"
            for 档 in (3, 2, 1, 0)
        )
    )
    if 统计["待看"]:
        typer.echo(f"  {统计['待看']} 条标了 needs_review，等你确认")
    if 统计["隐去的私密条数"]:
        typer.echo(
            f"  {统计['隐去的私密条数']} 条私密记录没有显示（要看加 --include-private）"
        )
    if 统计["读不动的文件"]:
        typer.echo(f"  有 {len(统计['读不动的文件'])} 个文件读不进来，已跳过：")
        for 一行 in 统计["读不动的文件"]:
            typer.echo(f"    {一行}")

    说明 = "  双击这个文件就能用浏览器打开。"
    if 文件.parent == 库:
        说明 += "（它就在 vault 里，不会被 git 提交。）"
    typer.echo(说明)

    if 打开:
        webbrowser.open(文件.resolve().as_uri())


# ── life reindex ──────────────────────────────────────────────

@app.command()
def reindex(
    向量: bool = typer.Option(
        False, "--vectors", help="顺便重建向量索引（需要先配好向量接口）"
    ),
):
    """从 vault/now/ 里的 markdown 重建整个索引（索引删了也能跑）。"""
    结果 = index.重建索引()
    typer.echo(
        f"· 扫描 {结果['扫描']} 个记录文件，成功写入索引 {结果['成功']} 条。"
    )
    if 结果["失败"]:
        typer.echo(f"· 有 {len(结果['失败'])} 个文件没读进来（其它文件照常建好了）：")
        for 一行 in 结果["失败"]:
            typer.echo(f"    {一行}")

    if not 向量:
        return

    能, 原因 = llm.能向量()
    if not 能:
        typer.echo(f"· 向量索引没建：{原因}")
        return

    条数, 说明 = _重建向量()
    if 说明:
        typer.echo(f"· 向量索引：{说明}")
    else:
        typer.echo(f"· 向量索引：{条数} 条已重建（私密记录不参与，§8）")


def _重建向量() -> tuple[int, str]:
    """给所有非私密记录算一遍向量。返回（条数，出错说明）。"""
    任务 = config.读取任务("embed")
    连接 = index.连接索引()
    try:
        行们 = 连接.execute(
            "SELECT id, did, body FROM entries WHERE private = 0 ORDER BY ts"
        ).fetchall()
        if not 行们:
            return 0, "没有可建向量的记录"
        try:
            index.清空向量(连接)
            向量们, _token = llm.嵌入([f"{行['did']} {行['body']}" for 行 in 行们])
        except (llm.模型错误, llm.网络错误, config.配置错误) as 错误:
            return 0, f"失败（{错误}）"
        模型名 = 任务.model if 任务 else "?"
        for 行, 向量 in zip(行们, 向量们):
            index.写向量(连接, 行["id"], 向量, 模型名)
        return len(行们), ""
    finally:
        连接.close()


# ── 内部函数 ──────────────────────────────────────────────────


def _抽取并保存(
    输入: dict, *, 用假模型: bool, 图片: Path | None = None
) -> tuple[list[Path], dict]:
    """一次输入 → 抽取 → 写成 markdown → 进索引。

    返回（写出来的文件路径列表，抽取结果）。抽取结果里有 OCR 全文，
    处理图片的时候要用。
    """
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
        typer.echo(f"· {结果['备注']}")

    连接 = index.连接索引()
    try:
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


def _处理图片(输入: dict, vault: Path, 暂存图: Path | None, 结果: dict) -> None:
    """按设计处理图片：OCR 全文留下，原图删掉（除非用户说了 --keep-image）。"""
    if 暂存图 is None:
        return

    # OCR 全文和摘要写到 vault/media/ —— 这是那张图唯一的「原话」（§5.5）
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
        typer.echo(f"· 原图按你的要求留下了：vault/media/{目标.name}")
    else:
        暂存图.unlink(missing_ok=True)


def main() -> None:
    """`life` 这个命令的入口（pyproject.toml 里登记的）。"""
    _防止中文乱码或崩溃()
    app()


def _防止中文乱码或崩溃() -> None:
    """Windows 终端默认不是 UTF-8，碰到它打不出来的字符会直接让命令崩掉。

    这里把「打不出来的字符」降级成问号，而不是让整条命令失败。
    你什么都不用做，这段只是保险。
    """
    for 流 in (sys.stdout, sys.stderr):
        try:
            流.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    main()
