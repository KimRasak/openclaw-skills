---
name: agent-session-inspector
description: >-
  Locate, inspect, search, and parse local conversation history across three AI
  coding agents: DeepSeek Harness (DSH), Cursor/VSCode Codex extension, and
  VSCode/Cursor Google Antigravity extension. Use when reviewing past prompts,
  auditing model usage, extracting conversation transcripts, or debugging
  session storage formats.
---

# Agent Session Inspector — 本地会话存储位置与查看指南

汇总 **DeepSeek Harness (DSH)**、**Cursor / VSCode Codex 插件**、**VSCode / Cursor Antigravity 插件** 三个 AI 编程助手在本地磁盘上的会话存储路径、数据格式及查看方法。

## 存储位置速查表

| 工具 / 插件 | 根目录 | 会话正文文件 / 数据库 | 索引 / 摘要缓存 | 压缩与编码格式 |
| :--- | :--- | :--- | :--- | :--- |
| **DeepSeek Harness (DSH)** | `~/.dsh/` | `~/.dsh/sessions/--<workspace-slug>--/<session-id>/session.v3.jsonl.zstd`（或旧版 `session.jsonl.zstd`） | `~/.dsh/storages/session_projcache/sessions/<session-id>.json` | `zstd` 压缩的 UTF-8 JSONL |
| **Cursor / VSCode Codex 插件** | `~/.codex/` | `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<session-id>.jsonl`（归档位于 `~/.codex/archived_sessions/`） | `~/.codex/session_index.jsonl`、`~/.codex/history.jsonl`、`~/.codex/state_5.sqlite` | 纯文本 UTF-8 JSONL |
| **VSCode / Cursor Antigravity 插件** | `~/.gemini/antigravity/`（CLI 为 `~/.gemini/antigravity-cli/`） | `~/.gemini/antigravity/brain/<conversation-id>/.system_generated/logs/transcript.jsonl` 及 `conversations/<conversation-id>.db` | `~/.gemini/antigravity/conversation_summaries.db`（含 FTS 全文检索表） | 纯文本 UTF-8 JSONL + SQLite (`.db`) |

---

## 快速使用（内置通用脚本）

本目录提供零外部依赖的通用解析脚本 `scripts/inspect_sessions.py`，支持统一列出、搜索和导出三个工具的会话：

```bash
# 1. 列出三个工具最近的会话（默认排除 subagent 子会话）
python3 agent-session-inspector/scripts/inspect_sessions.py list --tool all --limit 20

# 2. 只看某一个工具的会话（可选: dsh | codex | antigravity | all）
python3 agent-session-inspector/scripts/inspect_sessions.py list --tool dsh --limit 10

# 3. 查看指定会话 ID（支持前缀匹配）的完整多轮对话与所用模型
python3 agent-session-inspector/scripts/inspect_sessions.py show <session-id-prefix>

# 4. 只看用户在会话中说的话（过滤掉模型回复）
python3 agent-session-inspector/scripts/inspect_sessions.py show <session-id-prefix> --user-only

# 5. 跨工具搜索用户消息或助手回复中的关键词
python3 agent-session-inspector/scripts/inspect_sessions.py search "关键词" --tool all
```

---

## 1. DeepSeek Harness (DSH)

### 目录结构

```text
~/.dsh/
├── settings.yaml                                  # 模型路由与默认 Provider 配置
├── storages/
│   ├── workspace.json                             # 工作区列表
│   └── session_projcache/
│       └── sessions/<session-id>.json             # 会话投影缓存（标题、最后状态等）
└── sessions/
    └── --<workspace-path-with-dashes>--/          # 按工作区绝对路径转义分组
        └── <session-id>/
            ├── session.v3.jsonl.zstd              # 新版会话事件流（优先读取）
            ├── session.jsonl.zstd                 # 旧版会话事件流
            └── session.lock
```

### 核心事件格式（解压后每行一个 JSON）

- **注意切分行的方式**：部分 JSON 行内可能包含 Unicode 行分隔符（如 `\u2028`），在 Python 中解析时应使用 `out.split("\n")`，不要用 `out.splitlines()`。
- **区分主会话与子智能体（Subagent）会话**：
  - 首行 `{"type": "session", ...}` 中，主会话满足 `delegationDepth == 0` 且 `origin != "subagent"`。
  - 若 `isSeeded: true`，则 `seq <= end_seed_seq`（即 `{"type": "session/end-seed"}` 之前）的消息是从父会话继承的历史上下文，去重统计时应跳过。
- **提取真实用户输入**：
  - 事件类型为 `"type": "user/message"`。
  - `data.source.kind == "user"` 且 `data.source` 中包含 `"rpcId"`（有 `"rpcId"` 代表由人类用户在客户端真实发送，而非系统快照或子代理任务指令）。
  - 文本位于 `data.content` 数组中 `type == "text"` 的 `text` 字段。
- **提取当前轮次使用的模型**：
  - `"type": "model/selection"`：`data.provider` 与 `data.model`。
  - `"type": "request/header"`：`data.header.config.provider` 与 `data.header.config.model`。
  - `"type": "request/context"`：`data.provider` 与 `data.model`。
- **提取模型最终回复**：
  - 事件类型为 `"type": "assistant/message"`（流式增量事件如 `assistant/chunk`、`reasoning-chunks`、`text-chunks`、`tool-call-chunks` 可在快速解析时直接跳过）。
  - 文本位于 `data.message.content` 数组中 `type == "text"` 的 `text` 字段。

### 命令行直接查看

```bash
# 解压并查看某条会话的前 20 行事件
zstd -dc ~/.dsh/sessions/--<workspace>--/<session-id>/session.v3.jsonl.zstd | head -n 20

# 只提取该会话中人类用户发送的所有消息与时间
zstd -dc ~/.dsh/sessions/--<workspace>--/<session-id>/session.v3.jsonl.zstd \
  | jq -c 'select(.type=="user/message" and .data.source.rpcId != null) | {seq, time, text: [.data.content[]? | select(.type=="text") | .text] | join("\n")}'
```

---

## 2. Cursor / VSCode Codex 插件

Codex CLI 与 Cursor / VSCode 中的 Codex 插件共用 `~/.codex/` 目录存储所有会话。

### 目录结构

```text
~/.codex/
├── config.toml                                    # 默认模型、Provider 与安全策略
├── model_catalog.json                             # 可用模型目录定义
├── session_index.jsonl                            # 会话 ID、标题与更新时间索引
├── history.jsonl                                  # 用户历史输入记录
├── state_5.sqlite                                 # 线程状态 SQLite 数据库
├── sessions/
│   └── YYYY/MM/DD/
│       └── rollout-YYYY-MM-DDThh-mm-ss-<id>.jsonl # 按日期归档的完整会话事件流
└── archived_sessions/                             # 手动归档的会话文件
```

### 核心事件格式（每行一个 JSON）

- **会话元信息（`type == "session_meta"`）**：
  - `payload.id` / `payload.session_id`：会话 UUID。
  - `payload.cwd`：工作目录。
  - `payload.originator` / `payload.source`：入口来源（如 `"codex_vscode"` / `"vscode"` 表示来自 Cursor 或 VSCode 插件）。
  - `payload.base_instructions.provenance.model`：初始模型名。
- **模型与上下文切换**：
  - `type == "turn_context"`：`payload.model`、`payload.cwd`、`payload.effort`。
  - `type == "event_msg"` 且 `payload.type == "thread_settings_applied"`：`payload.thread_settings.model`。
- **用户输入消息**：
  - `type == "event_msg"` 且 `payload.type == "user_message"`：文本在 `payload.message`。
- **模型回复与耗时**：
  - `type == "event_msg"` 且 `payload.type == "task_complete"`：
    - `payload.last_agent_message`：本轮助手的最终回复文本。
    - `payload.duration_ms`：本轮端到端耗时（毫秒）。
    - `payload.error`：若本轮报错（如 403/429），包含具体错误对象。

### 命令行直接查看

```bash
# 查看所有会话索引
tail -n 20 ~/.codex/session_index.jsonl | jq .

# 提取某个 rollout 会话中的模型、用户提问与助手最终回复
jq -c '
  if .type == "turn_context" then {model: .payload.model}
  elif (.type == "event_msg" and .payload.type == "user_message") then {user: .payload.message}
  elif (.type == "event_msg" and .payload.type == "task_complete") then {assistant: .payload.last_agent_message, duration_ms: .payload.duration_ms, error: .payload.error}
  else empty end
' ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
```

---

## 3. VSCode / Cursor Antigravity 插件

Google Antigravity IDE 插件（以及终端工具 `agy`）将会话存储在 `~/.gemini/antigravity/` 和 `~/.gemini/antigravity-cli/` 下。

### 目录结构

```text
~/.gemini/antigravity/                             # IDE 插件与桌面端主目录（CLI 在 ~/.gemini/antigravity-cli/）
├── conversation_summaries.db                      # SQLite：会话摘要表 + FTS5 全文检索表
├── conversations/
│   └── <conversation-id>.db                       # SQLite：单会话轨迹表（steps, gen_metadata 等）
└── brain/
    └── <conversation-id>/
        ├── scratch/                               # 会话期间生成的临时脚本与预览产物
        └── .system_generated/
            ├── logs/
            │   ├── transcript.jsonl               # 纯文本 JSONL：完整对话步骤与 Token 统计
            │   ├── transcript_full.jsonl          # 含完整未截断工具输出的 JSONL
            │   └── media/                         # 多模态步骤读取的图片缓存
            └── steps/<step-idx>/output.txt        # 各步骤工具执行的标准输出文本
```

### 查看方式一：直接读取 `transcript.jsonl`（最直观，含 Token 明细）

每个会话对应的 `~/.gemini/antigravity/brain/<conversation-id>/.system_generated/logs/transcript.jsonl` 是纯文本 JSONL，主要行类型（`type` 字段）包括：

- **`USER_INPUT`**：用户输入，文本在 `content` 字段，时间在 `created_at`。
- **`PLANNER_RESPONSE`**：模型思考与回复，包含：
  - `content`：对用户展示的回复正文。
  - `thinking`：推理思考过程。
  - `tool_calls`：调用的工具列表与参数。
  - `input_tokens`、`cache_read_tokens`、`output_tokens`：单次调用的精确 Token 消耗。
- **`GENERIC` / `SYSTEM_MESSAGE`**：工具返回结果或系统消息。

```bash
# 查看某个 Antigravity 会话的用户输入与模型回复
jq -c 'select(.type == "USER_INPUT" or (.type == "PLANNER_RESPONSE" and .content != null)) | {step: .step_index, type, created_at, content}' \
  ~/.gemini/antigravity/brain/<conversation-id>/.system_generated/logs/transcript.jsonl
```

### 查看方式二：查询 `conversation_summaries.db`（适合快速检索全部会话）

`~/.gemini/antigravity/conversation_summaries.db` 是标准 SQLite 数据库，包含两张最常用的表：

1. **`conversation_summaries` 表**：
   - 字段：`conversation_id`, `title`, `preview`, `step_count`, `last_modified_time`, `workspace_uris`, `status`
2. **`conversations_fts` 表（FTS5 全文索引）**：
   - 字段：`conversation_id`, `chunk_index`, `title`, `workspace`, `user_body`（拼接好的用户发言）, `agent_body`（拼接好的模型回复）

```bash
# 列出所有 Antigravity 会话概览
sqlite3 -header -column ~/.gemini/antigravity/conversation_summaries.db \
  "SELECT conversation_id, title, step_count, workspace_uris FROM conversation_summaries;"

# 从全文索引表中直接查看用户发言与模型回复
sqlite3 ~/.gemini/antigravity/conversation_summaries.db \
  "SELECT conversation_id, chunk_index, user_body, substr(agent_body, 1, 500) FROM conversations_fts WHERE chunk_index >= 0;"
```
