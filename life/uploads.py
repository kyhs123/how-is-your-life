"""uploads.py —— 上传：解析表单、判断文件类型、从文档里抽文本。

为什么自己写 multipart 解析：
    标准库没有现成的（`cgi.FieldStorage` 在 3.13 被删了）。而只为一个上传框装
    `python-multipart`，等于给一个本机小工具加一条依赖链。所以按 RFC 7578 的
    最小子集自己解析——**规则写死在下面，不猜**。

三条硬规矩（docs/WEBUI.md §2.4）：
    1. 先落盘再处理
    2. 文件名不可信：只取扩展名，落盘名一律用记录 id
    3. 抽不出文本就说抽不出，不要存一条空记录
"""

from __future__ import annotations

import html as html模块
import re
import zipfile
from pathlib import Path

# ── 上限（和 docs/WEBUI.md §5.4 一致）───────────────────────

最大整体字节 = 12 * 1024 * 1024
最大单文件 = 8 * 1024 * 1024
最大字段字节 = 1 * 1024 * 1024
最大头部字节 = 8 * 1024
最大送模型字数 = 20000  # 文档全文另外存，送模型的部分截断

图片后缀 = (".png", ".jpg", ".jpeg", ".webp", ".gif")
文档后缀 = (".txt", ".md", ".docx")


class 上传错误(Exception):
    """上传内容有问题。报错话术直接给用户看。"""


# ── 解析表单 ─────────────────────────────────────────────────


def 解析(内容类型: str, 体: bytes) -> tuple[dict[str, str], list[dict]]:
    """把请求体拆成（普通字段，文件列表）。

    文件列表里每项：{"文件名": str, "类型": str, "数据": bytes}
    """
    if len(体) > 最大整体字节:
        raise 上传错误(f"这次提交太大了（上限 {最大整体字节 // (1024 * 1024)}MB）。")

    内容类型 = (内容类型 or "").strip()

    if 内容类型.startswith("application/x-www-form-urlencoded"):
        return _解析普通表单(体), []

    if 内容类型.startswith("multipart/form-data"):
        return _解析多段(内容类型, 体)

    raise 上传错误(f"不认识的提交格式：{内容类型 or '（没有）'}。")


def _解析普通表单(体: bytes) -> dict[str, str]:
    import urllib.parse

    文本 = 体.decode("utf-8", errors="replace")
    解析 = urllib.parse.parse_qs(文本, keep_blank_values=True)
    return {键: 值[0] for 键, 值 in 解析.items()}


def _取边界(内容类型: str) -> bytes:
    匹配 = re.search(r'boundary="?([^";]+)"?', 内容类型, re.I)
    if not 匹配:
        raise 上传错误("上传缺少边界标记（boundary），没法解析。")
    值 = 匹配.group(1).strip()
    if not 值 or len(值) > 70:
        raise 上传错误("上传的边界标记不正常。")
    return 值.encode("latin-1", errors="replace")


def _解析多段(内容类型: str, 体: bytes) -> tuple[dict[str, str], list[dict]]:
    边界 = _取边界(内容类型)
    分隔 = b"--" + 边界

    段们 = 体.split(分隔)
    if len(段们) < 3:
        raise 上传错误("上传的内容不完整（找不到结束标记）。")

    字段: dict[str, str] = {}
    文件们: list[dict] = []

    # 第一段是开头的空段，最后一段以 b"--" 开头（结束标记），中间才是内容
    for 段 in 段们[1:-1]:
        if 段.endswith(b"--"):
            continue
        段 = 段.lstrip(b"\r\n")
        if not 段:
            continue

        头块, 分隔符, 数据 = 段.partition(b"\r\n\r\n")
        if not 分隔符:
            raise 上传错误("上传的某一段没有头也没内容，解析不了。")
        if len(头块) > 最大头部字节:
            raise 上传错误("上传的头部信息太长，不像正常的表单。")

        # 数据末尾有一个 CRLF 属于分隔符，不属于内容
        if 数据.endswith(b"\r\n"):
            数据 = 数据[:-2]

        信息 = _解析头(头块)
        名字 = 信息.get("名字")
        if not 名字:
            continue  # 没名字的段没用，跳过

        文件名 = 信息.get("文件名")
        if 文件名:
            if len(数据) > 最大单文件:
                raise 上传错误(
                    f"文件太大了（上限 {最大单文件 // (1024 * 1024)}MB）。"
                )
            文件们.append(
                {"文件名": 文件名, "类型": 信息.get("类型", ""), "数据": 数据}
            )
        else:
            if len(数据) > 最大字段字节:
                raise 上传错误("某个输入框的内容太大了。")
            字段[名字] = 数据.decode("utf-8", errors="replace")

    return 字段, 文件们


def _解析头(头块: bytes) -> dict[str, str]:
    """从 `Content-Disposition` 里取字段名和文件名。"""
    结果: dict[str, str] = {}
    for 行 in 头块.decode("utf-8", errors="replace").splitlines():
        行 = 行.strip()
        if not 行 or ":" not in 行:
            continue
        键, _, 值 = 行.partition(":")
        键 = 键.strip().lower()

        if 键 == "content-disposition":
            结果["类型"] = ""
            匹配名 = re.search(r'\bname="([^"]*)"', 值)
            if 匹配名:
                结果["名字"] = 匹配名.group(1)
            # 只认 filename="..."；filename*= 这种 RFC 2231 形式先不支持（浏览器一般用前者）
            匹配文件 = re.search(r'\bfilename="([^"]*)"', 值)
            if 匹配文件 and 匹配文件.group(1).strip():
                结果["文件名"] = _清洗文件名(匹配文件.group(1))
        elif 键 == "content-type":
            结果["类型"] = 值.strip()

    return 结果


def _清洗文件名(名字: str) -> str:
    """只留「最后一段」，挡掉 ../ 和 windows 路径。"""
    名字 = 名字.replace("\\", "/").split("/")[-1]
    名字 = 名字.replace("\x00", "").strip()
    return 名字[:120] or "未命名"


# ── 判断类型 ─────────────────────────────────────────────────


def 判定(文件名: str, 数据: bytes) -> tuple[str, str]:
    """返回（"image" | "document", 后缀）。

    只按扩展名 + 魔数判断，**不信 Content-Type**（浏览器给的经常是 octet-stream）。
    """
    后缀 = Path(文件名).suffix.lower()

    if 后缀 in 图片后缀:
        if not _是图片(数据, 后缀):
            raise 上传错误(f"这个文件叫 {后缀}，但内容不像图片。是不是改过后缀？")
        return "image", 后缀

    if 后缀 in 文档后缀:
        if not 数据:
            raise 上传错误("这个文件是空的。")
        if 后缀 == ".docx" and not _是docx(数据):
            raise 上传错误("这个 .docx 打不开——它不是有效的 Word 文件（.doc 老格式也不支持）。")
        return "document", 后缀

    支持 = "图片（png / jpg / webp / gif）、文档（txt / md / docx）"
    raise 上传错误(f"不支持这种文件：{后缀 or '（没有扩展名）'}。现在支持 {支持}。")


def _是图片(数据: bytes, 后缀: str) -> bool:
    开头 = 数据[:16]
    if 后缀 == ".png":
        return 开头.startswith(b"\x89PNG\r\n\x1a\n")
    if 后缀 in (".jpg", ".jpeg"):
        return 开头.startswith(b"\xff\xd8\xff")
    if 后缀 == ".gif":
        return 开头.startswith((b"GIF87a", b"GIF89a"))
    if 后缀 == ".webp":
        return 开头.startswith(b"RIFF") and 数据[8:12] == b"WEBP"
    return False


def _是docx(数据: bytes) -> bool:
    if not 数据.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(_内存文件(数据)) as 包:
            return "word/document.xml" in 包.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def _内存文件(数据: bytes):
    import io

    return io.BytesIO(数据)


# ── 从文档里抽文本 ───────────────────────────────────────────


def 抽文本(路径: Path) -> str:
    """把文件里的文字抽出来。抽不出就抛错，不要返回空字符串糊弄人。"""
    后缀 = 路径.suffix.lower()

    if 后缀 in (".txt", ".md"):
        return _读纯文本(路径)

    if 后缀 == ".docx":
        return _读docx(路径)

    raise 上传错误(f"不知道怎么从 {后缀} 里抽文字。")


def _读纯文本(路径: Path) -> str:
    数据 = 路径.read_bytes()
    if len(数据) > 最大单文件:
        raise 上传错误("文件太大。")
    # 明显是二进制就别硬读
    if b"\x00" in 数据[:1024]:
        raise 上传错误("这个文件看着是二进制，不是纯文本。")
    for 编码 in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return 数据.decode(编码)
        except UnicodeDecodeError:
            continue
    raise 上传错误("这个文本文件的编码认不出来（试过 utf-8 和 gbk）。")


def _读docx(路径: Path) -> str:
    try:
        with zipfile.ZipFile(路径) as 包:
            原文 = 包.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as 错误:
        raise 上传错误(f"这个 Word 文件读不出来：{错误}") from 错误

    try:
        文本 = 原文.decode("utf-8")
    except UnicodeDecodeError as 错误:
        raise 上传错误(f"这个 Word 文件里的文字编码不对：{错误}") from 错误

    # 段落/换行先变真换行，再把标签全部剥掉
    文本 = re.sub(r"</w:p\s*>", "\n", 文本)
    文本 = re.sub(r"<w:br\s*/>", "\n", 文本)
    文本 = re.sub(r"<w:tab\s*/>", "\t", 文本)
    文本 = re.sub(r"<[^>]+>", "", 文本)
    文本 = html模块.unescape(文本)
    文本 = re.sub(r"[ \t]+\n", "\n", 文本)
    文本 = re.sub(r"\n{3,}", "\n\n", 文本)
    return 文本.strip()


def 送模型的片段(全文: str) -> str:
    """文档全文照存，但送给模型的那部分要截断（不然一次几十万 token）。"""
    全文 = 全文.strip()
    if len(全文) <= 最大送模型字数:
        return 全文
    return 全文[:最大送模型字数] + "\n\n（后面还有内容，太长没送进去。）"
