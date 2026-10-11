# Obsidian Assistant

中文 | [English](README.en.md)

面向 Obsidian 笔记库的轻量 Agent，支持知识库问答、论文阅读、笔记编辑与多论文综述。

项目 ReAct Agent 执行循环：模型决定搜索、阅读和工具调用，程序负责文件访问、上下文隔离与写入确认。Markdown 是知识来源，证据与草稿保存在独立工作区。

## 核心能力

| 场景 | 能力 |
| --- | --- |
| 知识库问答 | 搜索笔记、读取原文，回答事实、数字与实验设置 |
| 论文阅读 | 分页读取 PDF，生成论文笔记或会议审稿格式的 review |
| 文献综述 | 分配独立阅读子任务，汇集证据，比较方法并生成关联笔记 |
| 笔记维护 | 确认后新建或编辑笔记，检查出链、反链与未解析链接 |

提供 CLI 和 Streamlit 两个入口，共用 Agent 核心。网页支持持续会话、工具执行进度、写入确认卡片，以及中英文界面。

## Showcase：从论文文件夹生成综述

> 阅读 `papers/opd/` 中的论文，在 `survey/opd/` 生成简短综述，说明问题背景、核心方法与具体差异。复杂方法另写成笔记；背景概念第一次出现时，链接到库中已有的对应笔记。

网页上一次综述的开头。上面是问题，下面是前 8 步：读取技能、写入计划、派出子任务，再读回证据。这一轮一共 44 步。

![一次综述的工具步骤](assets/trace_example.png)

一次整理后的 `survey/overview.md`：论文笔记、方法笔记，以及指向库中已有概念的链接。

![survey/overview.md](assets/survey.png)

执行流程：

1. **加载技能与扫描文件**：读取 `survey`，定位 PDF 并组织论文清单。
2. **隔离阅读与保存证据**：子任务独立阅读，将证据和草稿写入指定工作目录。
3. **比较与整合**：主 Agent 接收状态、产物路径和短报告，按需取证，组织综述并关联已有笔记。
4. **确认与校验**：用户确认后写入知识库，检查未解析链接。

单篇论文的工具结果留在子任务中，主上下文保留协调信息与材料入口，通过工作文件传递证据。

其他示例：

> 根据库中的 PPO 笔记解释 clipping 的作用，并指出依据。

> 查看这篇笔记的反向链接，以及指向尚未创建笔记的链接。

示例路径需替换为自己的笔记库内容。

## 架构设计

| 机制 | 实现 |
| --- | --- |
| 模型驱动的执行循环 | 执行工具调用，将结果或错误返回模型，直到生成最终回答 |
| Skill 按需加载 | 系统提示只列出技能名称与简要描述，确认任务意图后按需读取 Skill 正文 |
| 工具延迟加载 | 非常驻工具 Schema 通过 `tool_describe` 或技能声明加载 |
| 子任务上下文隔离 | `run_subtask` 使用空上下文，通过任务说明与产物路径协作 |
| 文件访问边界 | 笔记库保存笔记与 PDF。工作区是该库里的 `.assistant/`，保存技能、会话和任务材料 |
| 上下文外置 | 估算超过 40000 token 时，更早的工具结果写入工作区，历史留下片段和路径；超过 100000 时，最近一批也同样处理 |
| 执行观测 | Streamlit 展示工具进度；可将完成轮次的 Trace 发送至 Langfuse |

子任务不继承主对话或技能正文，由父任务显式传入规则；只能写指定工作目录，不能修改笔记库或创建下级子任务。

### 检索与文件操作

- **检索**：BM25 + Markdown 切块 + jieba 中英文分词。搜索片段用于定位，回答依据来自后续读取的原文。
- **分页读取**：笔记与工作文件每次最多 80 行，PDF 每次最多 4 页。
- **知识链接**：实时解析 Obsidian 维基链接，支持出链、反链与未解析链接。
- **写入边界**：笔记库修改需要确认；工作区 `write_file` 直接写入 Markdown，拒绝写入 `skills/` 和 `sessions/`。
- **会话管理**：网页保留历史，超过压缩门槛后才外置工具结果；终端每问独立，不经过会话压缩。

### 内置技能

| 技能 | 用途 |
| --- | --- |
| `research` | 根据已有笔记回答事实、配置与实验设置 |
| `paper-note` | 将单篇 PDF 整理为论文笔记 |
| `paper-review` | 按会议审稿表组织 review |
| `survey` | 阅读多篇 PDF，生成综述与相关笔记 |

默认技能位于 `src/skills/default/`，启动时复制缺失文件到工作区，保留已有本地修改。技能正文现读现用；修改目录描述后需重启。

## 快速开始

需要 **Python 3.13** 和 [uv](https://docs.astral.sh/uv/)。

```powershell
uv sync
```

首次启动缺少密钥时，程序会提示填写并写入 `.env`，也可以手动创建：

```dotenv
OPENAI_API_KEY=your_openai_api_key
VAULT=

# 可选：模型和接口。不写则用 gpt-5 与 https://api.openai.com/v1
# OPENAI_MODEL=gpt-5
# OPENAI_BASE_URL=https://api.openai.com/v1

# 可选：启用 Langfuse
LANGFUSE_PUBLIC_KEY=your_langfuse_public_key
LANGFUSE_SECRET_KEY=your_langfuse_secret_key
```

环境变量优先于 `.env`。没写 `OPENAI_MODEL` 或 `OPENAI_BASE_URL` 时，使用 `gpt-5` 和 `https://api.openai.com/v1`，通过 OpenAI Chat Completions 调用。改完要重启。

`VAULT` 为空时，第一次启动会要求选择笔记库文件夹。终端弹出系统窗口，取消后可以粘贴路径。网页上点「浏览文件夹」。侧边栏的「更换笔记库」（英文界面是 Change vault）会改写这一行。选中的绝对路径写在 `.env` 的 `VAULT`，下次启动直接用。工作区建在该库的 `.assistant/`，笔记搜索不会读到它。

启动：

```powershell
# CLI
uv run python main.py

# Web
uv run streamlit run ui/app.py
```

终端里重新选择笔记库：

```powershell
uv run python main.py --vault
```

终端输入空行或 `quit` 退出，输入 `yes` 确认笔记修改；网页使用确认卡片。修改代码或技能目录后需重启进程。

步数和压缩门槛可以改项目根目录的 `settings.toml`。没有这个文件，或某一行没写，就用程序里的默认值。可改的项写在 `settings.example.toml`：主 Agent 的 `max_steps`（128）、子任务的 `subtask_steps`（40）、开始外置的 `compact_light`（40000）、最近一批也外置的 `compact_heavy`（100000）。改完要重启。终端每问独立，不压缩，所以后两项只影响网页和评测。

## 评测与测试

```powershell
# 查看任务，不调用模型
uv run python benchmark/run.py --list

# 按类别或任务运行
uv run python benchmark/run.py --category note-qa
uv run python benchmark/run.py --id ppo-clip

# 完整评测与单元测试
uv run python benchmark/run.py
uv run pytest
```

任务定义在 `benchmark/tasks.json`。完整评测生成 `benchmark/last_run.json` 和 `benchmark/last_run.html`，过滤运行不覆盖完整结果。

评测会调用模型 API。测试库不在仓库里，`uv run python benchmark/build_test_vault.py` 会生成 `benchmark/test_vault/`，并替换已有的那个目录。单元测试在 `tests/`，不纳入版本控制。

## 代码结构

| 路径 | 职责 |
| --- | --- |
| `src/entry.py` | Agent 构建与工具配置 |
| `src/config.py` | 笔记库路径，以及 `settings.toml` 里的步数和压缩门槛 |
| `src/agent/` | 执行循环、Context、模型接口与 Trace |
| `src/tools/` | 工具注册与文件操作 |
| `src/retrieval/` | Markdown 切块与 BM25 |
| `src/skills/default/` | 默认任务技能 |
| `src/sessions.py` / `src/compact.py` | 会话管理与结果外置 |
| `ui/` | Streamlit 界面、文案和工具步骤 |
| `benchmark/` | 评测任务与报告 |