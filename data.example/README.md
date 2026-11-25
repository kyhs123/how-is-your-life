# data.example —— 虚构的示例数据

这不是任何人的真实记录，是编的：一个在学后端的学生的半年（2026-09 ~ 2026-11）。

用来：
1. 让 `life demo` 一条命令就能看到「攒了半年数据之后长什么样」
2. 当抽取 prompt 的 few-shot 参考（这些 entry 的写法就是「带锚点的压缩」的样子）

包含：18 条 entry（跨 3 个月、含情绪与锚点）、2 个章节、1 个目标、5 条底色、2 份画像（含 diff）、1 份季度回顾 HTML。

灌进 vault 看效果：

```powershell
.\.venv\Scripts\life.exe demo
```

想单独看那份回顾 HTML：用浏览器打开本目录下的 `review-2026-Q4.html`。
