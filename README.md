# How Is Your Life「你过得怎么样」

**一个本地运行的人生记录工具。** 你写下自己做了什么、在想什么，它把内容压成带锚点的一句话，分层存好；在你需要的时候，把「你曾经做到过」的证据递到你手上。

核心不是记录，是**在正确的时刻把证据递给你**。所有笔记软件都负责存下来，没有一个负责在你想不起来的时候提醒你。

> ⚠️ **这不是心理咨询。** 它不诊断、不评估、不给你贴标签。真撑不住的时候，请找人，或者打心理援助热线。
>
> 还有一条底线写在设计文档里：如果它永远耐心、永远记得、永远不评判，**真人会显得很差**。这个产品不该成为你不找真人的理由——它会在合适的时候把你推回现实：「这件事你要不要跟你导师说一句？」

---

## 打开它：双击一下

**双击仓库根目录的 `启动.bat`。** 黑窗口起来，浏览器自己打开首页。**关掉那个黑窗口就是退出。**

| 你想干的事 | 怎么做 |
|---|---|
| 打开 | 双击 `启动.bat` |
| 发现它已经开着 | 再双击一次也没事，只会把浏览器再叫出来 |
| 退出 | 关掉那个黑窗口（按了 Ctrl+C 会问 `Terminate batch job (Y/N)`，打 `Y` 回车也行） |
| 想要桌面图标 | 右键 `启动.bat` → 发送到 → 桌面快捷方式 |
| 端口 8770 被别的程序占了 | `.\.venv\Scripts\life.exe server --port 8771` |

不用记命令。下面那些命令行只是「同一件事的另一种说法」。

---

## 现在做到哪了

| 周 | 功能 | 状态 |
|---|---|---|
| 1 | 录入 + 抽取 + 索引 + 只读看板 | ✅ |
| 2 | 三路检索 + `life ask`（**项目的验证点**：它能不能提起你忘掉的事） | ✅ |
| 3 | 目标 + 证据视图 + 固化（`settle`）+ 晋升（`promote`） | ✅ |
| 4 | 画像 + 回顾（含单文件 HTML）+ 示例数据 | ✅ |
| 5 | 可编辑的本机网页界面（`life server`：记一条 / 翻记录 / 提问 / 目标 / 主题 / 画像） | ✅ |

---

## 30 秒看到效果

不用配任何密钥，一条命令灌入一份**虚构的半年记录**（一个在学后端的学生）：

```powershell
.\.venv\Scripts\life.exe demo
```

然后：

```powershell
# 它能不能翻出你忘掉的事？（这是整个项目的验证点）
.\.venv\Scripts\life.exe ask "我好累，感觉半年什么都没做成"

# 一个目标的证据分布 —— 注意：没有百分比
.\.venv\Scripts\life.exe goal show 1

# 网页看板，双击就能看
.\.venv\Scripts\life.exe board --open

# 季度回顾，单文件 HTML
.\.venv\Scripts\life.exe review --quarter --html --out 回顾.html

# 主界面：浏览器里记一条、翻记录、提问、管目标
.\.venv\Scripts\life.exe server --open
# → http://127.0.0.1:8770/
```

`life ask` 的输出长这样（真跑出来的）：

> 累是真的。但「什么都没做成」这个结论我不认——2026-11-22 你跑了 5 公里，配速 6 分，比上个月还快了一点，这不是没做成。2026-09-26 你也说过「我是不是就这样了」，那次记录里只有崩溃；这次往前翻，至少还有一条往上走的。要不要今晚只把跑步那条备注成「比上个月快」，别的先不动？不想弄就睡。

---

## 网页界面（主界面）

```powershell
.\.venv\Scripts\life.exe server --open      # 打开 http://127.0.0.1:8770/
```

| 页面 | 能做什么 |
|---|---|
| 今天 | 写一句话记下来，或传一张图 / 一个文件；**可以补记过去**（「什么时候」留空=现在，也能写 `2023-09`、甚至「大一」） |
| 记录 | 翻全部记录，按类型/档位筛选，按月分组 |
| 单条 | 看全部字段，改那句话 / 档位 / 结果 / 状态 |
| 提问 | 输一句话，它翻出旧记录并回答（也可以只看翻到了什么）。**「我这周都做了什么」也在这儿问** |
| 目标 | 立目标、改目标、看证据卡；**也能直接把为这个目标做的事记进去**；旁边还有个**「问老师」**——它只看这个目标的证据，帮你定下一步 |
| 主题 | 系统把同一件事的记录串成一条线，提名给你，**点「要 / 不要」确认** |
| 画像 | 看最近一份季度画像 + **一键生成**（后台跑，页面自刷进度） |
| 设置 | 数据目录、模型、条数、token |

只绑 `127.0.0.1`：局域网里的手机和别的电脑连不上；不起外网服务、不引前端框架、无外部资源。
能改什么、不能改什么，见施工图 [docs/WEBUI.md](docs/WEBUI.md)。

界面长什么样：[首页](docs/screenshots/首页.png) ｜ [记录](docs/screenshots/记录.png)。
样式规则（纸色 + 墨色 + 一个强调色、三级字体、靠留白分区）在 [docs/WEBUI.md](docs/WEBUI.md) §4。

## 安装（三步）

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

装完之后命令在 `.\.venv\Scripts\life.exe`。想只敲 `life`，先执行一次 `.\.venv\Scripts\Activate.ps1`（提示「禁止运行脚本」就用完整路径，一样好使）。

### 接上模型（可选，但抽取需要）

```powershell
copy providers.example.yaml providers.yaml   # 改 base_url 和模型名
copy .env.example .env                       # 填 CHAT_API_KEY
```

`providers.yaml` 和 `.env` 都在 `.gitignore` 里，不会上传。

> **踩过的坑（一）**：思考型模型（带 reasoning 的）`max_tokens` 给小了，会把额度全花在「想」上、正文一个字都出不来（`finish_reason=length`）。写长文的任务给足 `max_tokens`。
>
> **踩过的坑（二）**：**`temperature` 要按任务配**。抽取要稳（0.2），对话要有温度（0.7）。全局写死 0.2 会让回答像在读台账。
>
> **踩过的坑（三）**：**模型的选择直接决定等待时间**。实测同一句提问，`deepseek-v4-pro` 36.5 秒、`glm-5.3-flash` 13.6 秒，质量都合格。默认配置用后者；想换回深思模型改 `providers.yaml` 的 `tasks.dialogue` / `tasks.settle` 一行即可。

---

## 命令一览

| 命令 | 干什么 |
|---|---|
| `life add "…"` | 记一件事（`--when` 什么时候 / `--image` 图片 / `--file` 文档 / `--emotion` / `--private` / `--demo`） |
| `life retry` | 把没抽成功的补抽一遍（断网时用） |
| `life ask "…"` | 带着旧记录回答；`--dry-run` 只看召回了什么 |
| `life board` | 生成单文件网页看板 |
| `life goal add/list/show/done/stop` | 目标与证据视图 |
| `life settle --week` | 归纳主题，够条件的写成晋升提名 |
| `life promote` | 处理提名：要 / 不要 |
| `life portrait [--diff]` | 季度画像（写假设，不写判决） |
| `life review [--week\|--quarter] [--html]` | 回顾 |
| `life demo` | 灌入虚构示例数据 |
| `life server` | 本机网页界面（主界面）：记一条、翻记录、提问、管目标（只绑 127.0.0.1） |
| `life reindex [--vectors]` | 从 markdown 重建索引 |
| `life tidy [--dry-run]` | 瘦身：清旧缓存和孤儿全文（记录一条都不动） |

---

## 功能与代码对照

| 功能 | 说明文档 | 主要代码 |
|---|---|---|
| vault 结构 | [vault结构.md](docs/features/vault结构.md) | `life/store.py` |
| 录入 | [录入.md](docs/features/录入.md) | `life/cli.py`、`life/store.py` |
| 抽取 | [抽取.md](docs/features/抽取.md) | `life/extract.py`、`life/llm.py`、`life/prompts/` |
| 索引 | [索引.md](docs/features/索引.md) | `life/index.py` |
| 三路检索 | [检索.md](docs/features/检索.md) | `life/retrieve.py` |
| 对话 | [对话.md](docs/features/对话.md) | `life/ask.py`、`life/prompts/ask.md` |
| 目标 | [目标.md](docs/features/目标.md) | `life/goal.py` |
| 固化与晋升 | [晋升.md](docs/features/晋升.md) | `life/promote.py`、`life/prompts/settle.md` |
| 画像 | [画像.md](docs/features/画像.md) | `life/portrait.py`、`life/prompts/portrait.md` |
| 回顾 | [回顾.md](docs/features/回顾.md) | `life/review.py`、`life/prompts/review.md` |
| 看板 | [看板.md](docs/features/看板.md) | `life/board.py` |
| 示例数据 | [示例数据.md](docs/features/示例数据.md) | `life/cli.py`、`data.example/` |
| 网页界面 | [网页编辑.md](docs/features/网页编辑.md)（施工图：[WEBUI.md](docs/WEBUI.md)） | `life/server.py`、`life/pages.py` |
| 假模型 | [假模型.md](docs/features/假模型.md) | `life/fake_model.py` |

完整索引见 [docs/features/README.md](docs/features/README.md)。设计文档：[docs/DESIGN.md](docs/DESIGN.md)。拍过的决定：[docs/决策记录.md](docs/决策记录.md)。

---

## 隐私

| 项 | 说明 |
|---|---|
| 数据在哪 | 全在你本机 `vault/`，纯文本 markdown，随时能拷走 |
| 哪些数据出网 | **只有「抽取」「对话」「画像」「回顾」「固化」这几步**会把相关文本发给你自己配置的模型接口 |
| 发到哪 | 你自己在 `providers.yaml` 里写的那个地址（本项目不自带任何服务端） |
| `--private` | 该条记录**一个字节都不发**，也不进检索、不进索引向量（有测试保证） |
| 密钥 | 只在 `.env` / 环境变量里，代码只读环境变量；`.env` 永不进仓库 |
| 遥测 | 零。不统计、不回传、不联网检查更新 |
| 图片 | 不存原图。抽取完只留 OCR 全文 + 摘要（`--keep-image` 才例外） |

`vault/`、`.env`、`providers.yaml`、`*.sqlite` 都在 `.gitignore` 里；`.githooks/pre-commit` 还会在提交前拦一道。

---

## 它不是什么

- ❌ 简历生成器（简历是顺带产物）
- ❌ 待办清单 / 习惯打卡（靠负罪感驱动是这类项目头号死因）
- ❌ 心理咨询
- ❌ AI 夸夸机（每次说「你已经很棒了」的产品，三天被关掉）
- ❌ 云同步服务、账号系统、社交功能

---

## 代码结构

```
life/           程序本体
  cli.py        命令入口
  store.py      markdown / inbox 读写（真相源）
  index.py      SQLite 索引（可重建）
  extract.py    抽取
  retrieve.py   三路检索
  ask.py        对话与输出校验
  goal.py       目标与证据
  promote.py    固化与晋升
  portrait.py   季度画像
  review.py     回顾（含 HTML）
  board.py      只读看板
  server.py     本机网页界面（路由 + 安全）
  pages.py      网页的渲染层（只拼 HTML，不碰磁盘）
  recorder.py   记一条的完整链路（CLI 与网页共用）
  uploads.py    上传：multipart 解析、类型判定、docx/txt 抽文本
  jobs.py       后台任务：长任务点按钮跑，页面自刷看结果
  tidy.py       瘦身：清旧缓存/孤儿全文（只删能重建的）
  llm.py        模型网关（三级降级 + 向量）
  config.py     配置
  prompts/      所有 prompt（纯文本）
data.example/   虚构的半年记录（life demo 用）
tests/          测试（全部从命令行验证用户能看到的结果）
docs/           设计 + 功能说明 + 学习总结 + 决策记录
vault/          你的数据（不进仓库）
```
