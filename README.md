# WXDashboard

微信群消息管理仪表盘 — 将所有工作群的聊天记录转化为可检索、可筛选、可分析的结构化台账。

![架构]
本地微信加密DB → [wx-cli] → sync_engine → SQLite + FTS5 → Flask API → 浏览器SPA

## 功能

- **消息同步** — 通过 wx-cli 读取本地微信数据库，增量/全量拉取群聊消息
- **分类管理** — 按项目特点灵活配置群组分类体系，支持子分类。典型项目管理模式:总承包/各分包
- **全文检索** — FTS5 全文索引，覆盖群名、发送人、消息内容
- **联系人提取** — 正则自动提取消息中的邮箱和手机号
- **多项目支持** — 标题下拉切换项目，可扩展至任意项目管理
- **零依赖前端** — 原生 JS SPA，无框架，响应式布局

## 快速开始

### 前置条件

- Windows / macOS / Linux
- Python 3.9+
- Node.js（用于安装 wx-cli）

### 安装

```bash
# 1. 克隆项目
git clone <repo-url>
cd WXDashboard

# 2. 创建虚拟环境并安装依赖
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
# .venv\Scripts\activate       # Windows
pip install -r requirements.txt

# 3. 安装 wx-cli（从本地微信数据库读取消息）
npm install -g wx-cli
wx init                        # 初始化 wx-cli，读取微信 MSG.db
```

### 启动

```bash
# Linux/macOS
python -m backend.app

# Windows — 双击运行
start_ledger.bat
```

浏览器打开 `http://127.0.0.1:8888`

## 架构

```
┌─────────────────────────────────────────────────────┐
│                    前端 (SPA)                        │
│  dashboard.html  +  app.js  +  style.css            │
│  分类筛选 | 表格视图 | 抽屉详情 | 搜索面板             │
└────────────────────┬────────────────────────────────┘
                     │ REST API (JSON)
┌────────────────────▼────────────────────────────────┐
│                  Flask (backend/app.py)               │
│  /api/groups  /api/messages  /api/search  /api/sync │
└────────────────────┬────────────────────────────────┘
                     │ SQL
┌────────────────────▼────────────────────────────────┐
│           SQLite + FTS5 (backend/database.py)        │
│  groups │ messages │ contacts │ sync_log │ fts      │
└────────────────────┬────────────────────────────────┘
                     │ subprocess
┌────────────────────▼────────────────────────────────┐
│           wx-cli (backend/sync_engine.py)            │
│  读取本地微信加密数据库 → JSON → 去重入库             │
└─────────────────────────────────────────────────────┘
```

### 数据流

```
微信MSG.db (加密)
    │
    ▼ wx sessions / wx history --json
JSON 消息数组
    │
    ▼ backend.sync_engine._upsert_from_wx_msg()
去重 (group_id + local_id)
    │
    ▼ backend.contact_extractor.extract_and_save()
正则提取 → 联系人表
    │
    ▼ backend.database.upsert_message()
messages 表 + FTS5 索引 (触发器自动同步)
    │
    ▼ Flask REST API
JSON 响应 → 浏览器渲染
```

### 核心模块

| 文件 | 职责 |
|------|------|
| `backend/sync_engine.py` | 调用 wx-cli，解析 JSON，类别推断，消息入库 |
| `backend/database.py` | SQLite schema，FTS5 全文搜索，CRUD 操作 |
| `backend/contact_extractor.py` | 正则提取邮箱和手机号 |
| `backend/app.py` | 13 个 REST 端点，Flask 开发服务器 |
| `backend/config.py` | 路径和端口配置 |
| `backend/import_legacy.py` | 旧版 Excel/JSON 台账导入 |

### 数据库表

```
groups          messages         contacts
┌──────────┐   ┌──────────┐    ┌──────────┐
│ id       │──▶│ group_id │    │ group_id │
│ name     │   │ local_id │───▶│sender_name│
│ category │   │ sender   │    │ email    │
│ sub_cat  │   │ content  │    │ phone    │
│ project  │   │ msg_time │    │confirmed │
│ creator  │   │ msg_date │    └──────────┘
│ last_date│   │ msg_type │
│ msg_count│   │ raw_json │    sync_log
└──────────┘   └──────────┘    ┌──────────┐
                                │group_name│
messages_fts (FTS5)             │sync_time │
┌──────────────┐                │pulled/new│
│ group_name   │                │status    │
│ sender       │                └──────────┘
│ content      │
└──────────────┘
```

## 常用命令

```bash
# 增量同步（日常使用）
python -c "from backend.sync_engine import sync_incremental; print(sync_incremental())"

# 全量拉取指定群
python -c "from backend.sync_engine import sync_full; print(sync_full('群名'))"

# 全量拉取全部群
python -c "from backend.sync_engine import sync_all_groups_full; sync_all_groups_full()"

# 发现新群组
python -c "from backend.sync_engine import discover_new_groups; print(discover_new_groups())"

# 全文搜索
python -c "from backend.database import search_messages; print(search_messages('关键词'))"

# 导入旧版台账
python -m backend.import_legacy
```

## 配置

编辑 `backend/config.py`：

```python
FLASK_HOST = "127.0.0.1"  # 监听地址
FLASK_PORT = 8888          # 端口
DB_PATH    = "data/ledger_v2.db"  # 数据库路径
```

## 扩展新项目

1. 在项目选择器中添加新项目选项（或通过 API `/api/projects` 自动发现）
2. 修改 `backend/sync_engine.py` 中的 `project_keywords` 匹配规则
3. 启动后使用"发现新群组"或"刷新消息"拉取数据
4. 群组会自动关联到指定项目

## 目录结构

```
WXDashboard/
├── backend/             # Python 后端包
│   ├── __init__.py
│   ├── app.py           # Flask 主应用
│   ├── config.py        # 配置文件
│   ├── database.py      # 数据层（SQLite + FTS5）
│   ├── sync_engine.py   # wx-cli 调用与同步逻辑
│   ├── contact_extractor.py # 联系人正则提取
│   └── import_legacy.py # 旧版数据导入
├── requirements.txt     # Python 依赖
├── start_ledger.bat     # Windows 启动脚本
├── .gitignore
├── static/
│   ├── app.js           # 前端 SPA 逻辑
│   ├── style.css        # 样式
│   └── favicon.svg
├── templates/
│   └── dashboard.html   # 主页面模板
├── data/
│   └── (SQLite 数据库，由 init_db() 自动创建)
└── .originfiles/         # 临时文件和 AI 产出备份
```

## Claude Code AI 助手

本项目通过 Claude Code（CLI 对话式 AI）在本地完成消息摘要、群组分类和信息提取。所有 AI 处理均在 Claude Code 会话中完成，不接入外部 API。

### 前置准备

```bash
# 安装 Claude Code 与微信消息摘要技能
npm install -g @anthropic-ai/claude-code
claude mcp add librarian           # 会话记忆归档（可选）
```

在项目根目录启动 Claude Code：

```bash
cd WXDashboard
claude
```

### 常用 AI 指令

以下为 Claude Code 会话中可下达的自然语言指令示例：

**群组智能分类**

```
帮我检查一下当前有哪些未分类的群组，根据当前项目的特点自动分类。
分类体系: 内部（总承包）包含内部沟通、施工局合作、设计院合作；
          外部（各分包）包含供应商询价、地基处理、建筑MEP、保险、物流。
不确定的标记为"待确认"，不要强行分类。
```

AI 会读取数据库中的群名和最近消息内容，结合项目合作方构成推断分类，通过 `/api/groups/<id>/subcategory` 写入。

**群聊摘要生成**

```
为所有消息数超过 50 条的群生成最近一周的聊天摘要。
```

AI 会调用 `baoyu-wechat-summary` 技能逐群生成结构化摘要（摘要内容、关键主题），写入 `ai_summaries` 表并生成 Markdown 备份。

**关键信息提取**

```
提取所有群最近一周消息中的关键信息，包括:
- 联系人信息（公司名、职位、联系方式）
- 技术参数（规格、标准、指标值）
- 工期节点（计划日期、里程碑）
- 文件/图纸引用（编号、版本、发布日期）
```

提取结果写入 `ai_extractions` 表，前端群详情页"关键信息"标签页可查看。

**自定义指令**

```
帮我总结一下"施工技术讨论"群最近三天关于混凝土施工方案的讨论要点。
```

你可以随意组合群名、时间范围和信息维度的限定，Claude Code 会从 `messages` 表读取相应消息并进行分析。

### 手动分类与 AI 跳过

在仪表盘群详情抽屉的"设置"标签页中，可以对群组手动指定项目和分类。勾选保存后设置 `manual_category=1` 标记，后续 AI 整理时会**跳过该项目和分类的自动调整**，但仍会执行摘要生成和关键信息提取等任务。点击"取消手动分类"可恢复 AI 自主管理。

### 新增 AI 能力

Claude Code 的技能系统支持扩展。要在项目中新增 AI 信息处理能力：

1. 在 `backend/database.py` 新增存储表或字段
2. 在 `backend/app.py` 新增 REST 端点
3. 在 `static/app.js` 新增前端渲染逻辑
4. 编写 Claude Code Skill（`*.md`）定义处理流程

## 设计理念

- **最小依赖** — 3 个 Python 库 + 1 个外部 CLI 工具
- **无框架前端** — 原生 JS，零构建步骤
- **SQLite 为主** — 不需要额外数据库服务
- **FTS5 全文搜索** — SQLite 内置，零配置
- **AI 辅助筛选** — Claude Code 会话内完成摘要和关键信息提取，不依赖外部 API

## License

MIT
