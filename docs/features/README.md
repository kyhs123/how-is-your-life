# 功能说明文档索引

每个功能都有一份说明，五节齐全：**这个功能对用户是什么 / 一次调用的完整路径 / 关键代码在哪 / 为什么这么设计 / 已知限制**。

| 功能 | 说明文档 | 主要代码 |
|---|---|---|
| vault 结构（记录存在哪） | [vault结构.md](vault结构.md) | `life/store.py` |
| 录入（life add） | [录入.md](录入.md) | `life/cli.py`、`life/store.py` |
| 抽取（一段话 → 档案卡） | [抽取.md](抽取.md) | `life/extract.py`、`life/llm.py`、`life/prompts/` |
| 索引（SQLite 目录页） | [索引.md](索引.md) | `life/index.py` |
| 假模型（--demo 演示） | [假模型.md](假模型.md) | `life/fake_model.py` |
| 看板（单文件网页，`life board`） | [看板.md](看板.md) | `life/board.py`、`life/cli.py` |
| 检索（三路混合） | [检索.md](检索.md) | `life/retrieve.py`、`life/index.py` |
| 对话（`life ask`） | [对话.md](对话.md) | `life/ask.py`、`life/prompts/ask.md` |
| 目标（`life goal`） | [目标.md](目标.md) | `life/goal.py`、`life/cli.py` |
| 固化与晋升（`life settle` / `life promote`） | [晋升.md](晋升.md) | `life/promote.py`、`life/prompts/settle.md` |
| 画像（`life portrait`） | [画像.md](画像.md) | `life/portrait.py`、`life/prompts/portrait.md` |
| 回顾（`life review`） | [回顾.md](回顾.md) | `life/review.py`、`life/prompts/review.md` |
| 示例数据（`life demo`） | [示例数据.md](示例数据.md) | `life/cli.py`、`data.example/` |
| 网页编辑（`life server`） | [网页编辑.md](网页编辑.md) | `life/server.py`、`life/goal.py` |

> 看板是把 §4.8「可选生成单文件 HTML」的展示部分提前做了，没有引入任何框架或服务端。

## 还没做的

五周计划已经全部交付。剩下的都是设计里明确「MVP 之后」的事（§10.2）：手机入口、语音输入、周年触发、面试模式、章节→底色的 50 条挤出机制。

还有 §3.2 的第二条晋升路线（章节 → 底色）没实现——它需要跨 ≥2 个完整章节 + 迁移证据，现在真实数据还凑不出来。
