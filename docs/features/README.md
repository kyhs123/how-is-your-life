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

> 看板是把 §4.8「可选生成单文件 HTML」的展示部分提前做了，没有引入任何框架或服务端。

## 还没做的（后面几周）

| 功能 | 计划周次 | 设计文档位置 |
|---|---|---|
| 目标 `life goal` + 证据视图 | 第 3 周 | §4.5 |
| `life settle` / `life promote` 晋升 | 第 3 周 | §4.6 / §3.2 |
| 情感记录深化 + 画像 `life portrait` | 第 4 周 | §4.7 / §7 |
| 回顾 `life review` + HTML | 第 4 周 | §4.8（展示部分已提前做成 `life board`） |
| README 完整版 + demo 数据 | 第 4 周 | §9.3 / §13 |
| 可编辑网页界面（`life server`） | 第 5 周 | §10 路线图 |
