# How Is Your Life「你过得怎么样」

一个**本地运行**的人生记录工具：你写下自己做了什么、在想什么，它把内容整理成精准的短记录，分层存好，在你需要的时候把「你曾经做到过」的证据递到你手上。

> ⚠️ **这不是心理咨询。** 它不诊断、不评估、不给你贴标签。真撑不住的时候，请找人，或者拨打心理援助热线。
>
> 另一条底线写在设计文档里：如果它永远耐心、永远记得、永远不评判，真人会显得很差。**这个产品不该成为你不找真人的理由。**

## 现在做到哪了

第 1 周：**录入 + 抽取 + 索引**。能记，能压缩，能建索引。
第 2 周的「三路检索 + `life ask`」才是这个项目的验证点——它能不能提起你忘掉的事。还没做。

功能清单和说明文档见 [docs/features/README.md](docs/features/README.md)；
完整设计见 [docs/DESIGN.md](docs/DESIGN.md)。

## 安装（三步）

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

装完之后，命令就在 `.\.venv\Scripts\life.exe` 这个位置。

**下面所有命令都写成 `.\.venv\Scripts\life.exe`，是因为它一定能跑。** 如果你想只敲 `life`，
先在这个终端里执行一次 `.\.venv\Scripts\Activate.ps1` 激活虚拟环境（如果提示「禁止运行脚本」，
那就别折腾了，用完整路径一样好使）。

## 试四条命令

在仓库根目录 `life-record\` 下打开 PowerShell：

```powershell
# 1. 记一条（用假模型，不联网不花钱）
.\.venv\Scripts\life.exe add "今天把 OAuth 调通了，卡在 state 参数签名，调了 4 小时" --demo

# 2. 打开生成的记录看看（路径会打印在上面，长这样）
#    vault/now/2026-11/20261125-162806.md

# 3. 生成一个网页看板，双击就能看所有记录
.\.venv\Scripts\life.exe board --open

# 4. 从 markdown 重建索引（索引删了也能跑）
.\.venv\Scripts\life.exe reindex
```

如果屏幕上中文变成乱码，先敲一次 `chcp 65001` 再试。

想用真 AI：把 `providers.example.yaml` 复制成 `providers.yaml`，把 `.env.example` 复制成 `.env`
并填上 `CHAT_API_KEY`，然后去掉 `--demo`。

## 隐私

- 所有数据都在你本机 `vault/` 目录里，纯文本，你随时能拷走。
- `vault/`、`.env`、`providers.yaml`、`*.sqlite` 都在 `.gitignore` 里，**永远不会被提交**。
- 出网范围：只有「抽取」这一步会把你的原文发给你自己配置的模型接口。加了 `--private` 的记录**一个字节都不发**。
- 零遥测，不做任何统计上报。

## 代码结构

```
life/         程序本体（cli 命令入口 / store 文件读写 / extract 抽取 / index 索引 / llm 模型网关 / board 看板）
life/prompts/ 抽取用的 prompt，纯文本，改它不用动代码
vault/        你的数据（不进仓库）
tests/        自动测试
docs/         设计文档 + 功能说明 + 学习总结
```
