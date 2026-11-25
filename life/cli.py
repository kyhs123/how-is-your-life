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
from life import goal as goal模块
from life import portrait as portrait模块
from life import promote as promote模块
from life import recorder as recorder模块
from life import review as review模块
from life import server as server模块

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
    文档: Optional[Path] = typer.Option(
        None, "--file", help="配一个文件（txt / md / docx），会先在本地抽出文字"
    ),
    情感: bool = typer.Option(False, "--emotion", help="这条是感受，不是做了什么"),
    私密: bool = typer.Option(
        False, "--private", help="只存本地，绝不发给任何接口（也不会被以后的检索翻出来）"
    ),
    保留图片: bool = typer.Option(
        False, "--keep-image", help="破例保留原图（设计默认不存原图）"
    ),
    保留文件: bool = typer.Option(
        False, "--keep-file", help="破例保留原文件（默认只留抽出来的文字）"
    ),
    演示: bool = typer.Option(False, "--demo", help="用假模型演示，不联网不花钱"),
):
    """记一件事。先把内容写进硬盘，再想办法压缩成一句话。"""
    if 图片 is not None and 文档 is not None:
        typer.echo("× --image 和 --file 一次只能给一个。")
        raise typer.Exit(1)

    if not 文本.strip() and 图片 is None and 文档 is None:
        typer.echo(
            '× 你什么都没输入。\n'
            '  用法：life add "今天做了什么"\n'
            '        life add --image 图片路径 "说明"\n'
            '        life add --file 文档.docx "说明"'
        )
        raise typer.Exit(1)

    if 演示:
        typer.echo("· 这次用的是假模型（--demo），不会真的调用 AI。")

    结果 = recorder模块.记录一条(
        文本,
        图片=图片,
        文档=文档,
        文档原名=文档.name if 文档 is not None else "",
        保留原文件=保留文件,
        情感=情感,
        私密=私密,
        保留图片=保留图片,
        用假模型=演示,
        提示=typer.echo,
    )

    状态 = 结果["状态"]
    if 状态 == "输入有问题":
        typer.echo(f"× {结果['错误']}")
        raise typer.Exit(1)
    if 状态 == "重复":
        return
    if 状态 == "抽取失败":
        typer.echo(f"· 抽取没成功，但记录已经存好了。\n  {结果['错误']}")
        typer.echo("  联网之后跑 `life retry` 就能补上。")
        return
    if 状态 == "配置错误":
        typer.echo(f"× {结果['错误']}")
        if 结果["收件"] is not None:
            typer.echo(f"  你的输入已经存好了：vault/inbox/{结果['收件'].name}")
        raise typer.Exit(1)

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
            路径们, 结果 = recorder模块.抽取并保存(输入, 用假模型=演示, 图片=暂存图, 提示=typer.echo)
        except (llm.模型错误, extract.抽取错误, index.索引错误, config.配置错误) as 错误:
            typer.echo(f"× {路径.name} 还是不行：{错误}")
            失败 += 1
            continue

        store.删inbox(路径)
        recorder模块.处理图片(输入, vault, 暂存图, 结果, 提示=typer.echo)
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


# ── life goal（目标，第 3 周）─────────────────────────────────

目标app = typer.Typer(
    help="目标（人生规划）：立目标、看证据分布。不做百分比，不催进度。",
    no_args_is_help=True,
)
app.add_typer(目标app, name="goal")


@目标app.command("add")
def goal_add(
    标题: str = typer.Argument(..., help="目标的名字，比如 \"学完后端基础\""),
    期限: str = typer.Option(
        "term", "--horizon", help="short（2周~1月）/ term（一学期~半年）/ long（1~3年）"
    ),
    为什么: str = typer.Option("", "--why", help="为什么想要它（将来你自己会想看这句）"),
    截止: str = typer.Option("", "--due", help="截止日期，形如 2027-01-15"),
):
    """立一个目标。"""
    try:
        目标 = goal模块.建目标(标题, 期限=期限, 为什么=为什么, 截止=截止)
    except store.存储错误 as 错误:
        typer.echo(f"× {错误}")
        raise typer.Exit(1) from 错误
    except goal模块.目标错误 as 错误:
        typer.echo(f"× {错误}")
        raise typer.Exit(1) from 错误

    typer.echo(f"√ 立好了：{目标['title']}")
    typer.echo(f"  文件：vault/goals/{目标['id']}.md")
    typer.echo("  记录里写的事会自动挂到目标名下（前提是抽取时认出了这个目标）。")


@目标app.command("list")
def goal_list():
    """列出所有目标。"""
    目标们 = goal模块.全部目标()
    if not 目标们:
        typer.echo('还没有目标。立一个：')
        typer.echo('  life goal add "学完后端基础" --horizon term --why "想自己能做一个网站"')
        return
    for 序号, 目标 in enumerate(目标们, start=1):
        typer.echo(goal模块.一行概览(序号, 目标))
    typer.echo("")
    typer.echo("看某张证据卡：life goal show 1")


@目标app.command("show")
def goal_show(标识: str = typer.Argument(..., help="目标的编号、名字或它的一部分")):
    """看一个目标的证据分布。"""
    try:
        目标 = goal模块.找目标(标识)
    except goal模块.目标错误 as 错误:
        typer.echo(f"× {错误}")
        raise typer.Exit(1) from 错误

    typer.echo("")
    typer.echo(goal模块.渲染卡片(目标))


@目标app.command("done")
def goal_done(标识: str = typer.Argument(..., help="目标的编号或名字")):
    """标记目标完成。你说完成就是完成，系统不校验证据——但卡片会照实展示分布。"""
    try:
        目标 = goal模块.改状态(标识, "done")
    except goal模块.目标错误 as 错误:
        typer.echo(f"× {错误}")
        raise typer.Exit(1) from 错误

    typer.echo(f"√ 标记完成：{目标['title']}")
    typer.echo("")
    typer.echo(goal模块.渲染卡片(目标))


@目标app.command("stop")
def goal_stop(
    标识: str = typer.Argument(..., help="目标的编号或名字"),
    原因: str = typer.Option("", "--reason", help="为什么不做了（写下来，将来有用）"),
):
    """停下目标。想换方向不是失败。"""
    try:
        目标 = goal模块.改状态(标识, "stopped", 原因=原因)
    except goal模块.目标错误 as 错误:
        typer.echo(f"× {错误}")
        raise typer.Exit(1) from 错误
    typer.echo(f"√ 已停：{目标['title']}" + (f"（原因记下了：{原因}）" if 原因 else ""))


# ── life settle / life promote（固化与晋升，第 3 周）───────────


@app.command()
def settle(
    周: bool = typer.Option(False, "--week", help="按最近 7 天归纳（默认就是这个）"),
    天数: int = typer.Option(7, "--days", help="看最近几天的记录"),
):
    """把最近这一段的记录归纳成主题，够条件的写成「晋升提名」。

    注意：这一步只提名，不动你的记录。要不要晋升，用 `life promote` 一条条决定。
    """
    try:
        结果 = promote模块.提名(天数=天数)
    except promote模块.晋升错误 as 错误:
        typer.echo(f"× {错误}")
        raise typer.Exit(1) from 错误

    if 结果["说明"]:
        typer.echo(f"· {结果['说明']}")
        return

    typer.echo(f"· 找到 {结果['主题数']} 个主题。")

    for 记录 in 结果["提名"]:
        typer.echo("")
        typer.echo(f"  √ 提名：{记录['标题']} → 章节")
        typer.echo(f"    依据：{promote模块._依据文字(记录)}")
        if 记录.get("摘要"):
            typer.echo(f"    摘要：{记录['摘要']}")

    for 记录 in 结果["没提名"]:
        typer.echo("")
        typer.echo(f"  · 暂不提名：{记录['标题']}")
        typer.echo(f"    原因：{记录['原因']}")

    if 结果["提名"]:
        typer.echo("")
        typer.echo("要确认这些提名：life promote")
    elif not 结果["没提名"]:
        typer.echo("· 这一段里没有值得提名的主题。")


@app.command()
def promote(
    全部是: bool = typer.Option(False, "--yes", help="全部确认，不一条条问"),
):
    """处理晋升提名：要 / 不要。绝不自动晋升。"""
    提名们 = promote模块.待确认提名()
    if not 提名们:
        typer.echo("· 没有等你处理的提名。先跑一次 `life settle --week`。")
        return

    typer.echo(f"· 有 {len(提名们)} 条提名等你决定。")
    晋升了 = 0
    拒绝了 = 0

    for 记录 in 提名们:
        标题 = 记录["标题"]
        typer.echo("")
        typer.echo(f"── {标题} " + "─" * 20)
        if 记录.get("摘要"):
            typer.echo(f"   摘要：{记录['摘要']}")
        typer.echo(f"   依据：{promote模块._依据文字(记录)}")
        typer.echo(f"   涉及 {记录['条数']} 条记录，最高 {记录['最高档']} 档")

        if 全部是:
            要 = True
        else:
            要 = typer.confirm("   要把它升成章节吗", default=False)
        if not 要:
            要 = False

        try:
            if 要:
                结果 = promote模块.确认(标题)
                晋升了 += 1
                typer.echo(f"   √ 已成为章节「{结果['章节']['id']}」，回填了 {len(结果['回填'])} 条记录")
            else:
                promote模块.拒绝(标题)
                拒绝了 += 1
                typer.echo("   · 拒绝了，以后不再提这一条")
        except promote模块.晋升错误 as 错误:
            typer.echo(f"   × {错误}")

    typer.echo("")
    typer.echo(f"· 完成：晋升 {晋升了} 条，拒绝 {拒绝了} 条。记录都在 vault/changelog.md 里。")


# ── life portrait / life review（画像与回顾，第 4 周）───────────


@app.command()
def portrait(
    只看变化: bool = typer.Option(False, "--diff", help="只看和上季度的变化"),
):
    """生成（或更新）本季度的画像。写的是假设，不是判决。"""
    if 只看变化:
        try:
            typer.echo(portrait模块.只看变化())
        except portrait模块.画像错误 as 错误:
            typer.echo(f"× {错误}")
            raise typer.Exit(1) from 错误
        return

    try:
        结果 = portrait模块.生成()
    except portrait模块.画像错误 as 错误:
        typer.echo(f"× {错误}")
        raise typer.Exit(1) from 错误

    typer.echo(f"√ {结果['季度']} 画像已生成：{结果['路径']}")
    typer.echo(f"  本次 {结果['token']} token")

    if 结果["缺依据的假设"]:
        typer.echo("")
        typer.echo(f"· 有 {len(结果['缺依据的假设'])} 条假设没写依据（模型在说场面话）：")
        for 一条 in 结果["缺依据的假设"]:
            typer.echo(f"    - {一条}")
        typer.echo("  （这些不是数据推出来的，信之前先怀疑一下。）")


@app.command()
def review(
    周: bool = typer.Option(False, "--week", help="回顾最近 7 天（默认）"),
    季度: bool = typer.Option(False, "--quarter", help="回顾本季度"),
    用html: bool = typer.Option(False, "--html", help="输出单文件 HTML，双击可看"),
    输出: Optional[Path] = typer.Option(None, "--out", help="写到文件（不写就打印到屏幕）"),
):
    """回顾一段时间：做了什么、证据分布变化、情绪、晋升、一个建议。"""
    try:
        文本, 数据 = review模块.生成(周=not 季度, 季度=季度, 用HTML=用html)
    except review模块.回顾错误 as 错误:
        typer.echo(f"× {错误}")
        raise typer.Exit(1) from 错误

    if 输出 is not None:
        输出.parent.mkdir(parents=True, exist_ok=True)
        输出.write_text(文本, encoding="utf-8")
        typer.echo(f"√ 回顾已写入：{输出}")
        if 用html:
            typer.echo("  双击这个文件就能用浏览器打开。")
    else:
        typer.echo(文本)


@app.command()
def demo(
    覆盖: bool = typer.Option(False, "--force", help="vault 里已经有记录也强行灌入"),
):
    """把 data.example/ 里的虚构数据灌进 vault，用来试功能（别往里写真的）。"""
    源 = config.示例数据目录()
    if not 源.exists():
        typer.echo(f"× 找不到示例数据：{源}")
        raise typer.Exit(1)

    目标 = store.确保vault就绪()
    已有 = list((目标 / "now").rglob("*.md"))
    if 已有 and not 覆盖:
        typer.echo(f"× vault 里已经有 {len(已有)} 条记录了——那是你自己的数据。")
        typer.echo("  示例数据会混进去，所以我不动手。三个选择：")
        typer.echo("    1. 换个地方试：设 LIFE_HOME 指到别的目录再跑（推荐）")
        typer.echo("    2. 确实想混进来：加 --force")
        typer.echo("    3. 不用示例数据，直接记你自己的")
        raise typer.Exit(1)

    份数 = 0
    for 文件 in sorted(源.rglob("*")):
        if not 文件.is_file() or 文件.name == "README.md":
            continue
        相对路径 = 文件.relative_to(源)
        (目标 / 相对路径).parent.mkdir(parents=True, exist_ok=True)
        (目标 / 相对路径).write_text(文件.read_text(encoding="utf-8"), encoding="utf-8")
        份数 += 1

    结果 = index.重建索引()
    typer.echo(f"√ 灌入 {份数} 个文件，索引进 {结果['成功']} 条记录、{结果['章节']} 个章节、{结果['目标']} 个目标。")
    typer.echo("· 这些是虚构数据（一个编程学习者半年的记录），不是你的。")
    typer.echo("  试试：life ask \"我好累，感觉什么都没做成\"")
    typer.echo("        life goal show 1")
    typer.echo("        life board --open")


# ── life server（本机网页界面，第 5 周）───────────────────────


@app.command()
def server(
    端口: int = typer.Option(8770, "--port", help="监听端口（只绑 127.0.0.1）"),
    打开: bool = typer.Option(False, "--open", help="启动后用浏览器打开"),
):
    """启动本机网页界面：新建/修改目标、确认待确认的记录。

    只做这两件事。只绑 127.0.0.1，局域网里的其它机器连不上。
    """
    try:
        typer.echo("· 正在准备…")
        server模块.启动(端口, 打开浏览器=打开)
    except OSError as 错误:
        typer.echo(f"× 端口 {端口} 用不了（可能被别的程序占了）：{错误}")
        typer.echo("  换个端口：life server --port 8771")
        raise typer.Exit(1) from 错误


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
    typer.echo(
        f"· 顺带重建：章节 {结果['章节']} 个、目标 {结果['目标']} 个、底色 {结果['底色']} 条。"
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
