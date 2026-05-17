# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

WXDashboard — 微信工作群消息管理系统。对所有工作微信群聊记录进行归档、检索与信息筛选管理。通过 `wx-cli` (npm) 读取本地微信数据库,经 `sync_engine.py` 解析写入 SQLite + FTS5 全文索引,Flask 提供 Web 仪表盘进行浏览和搜索。

## 常用命令

```bash
# 启动开发服务器
python -m backend.app                           # 启动 Flask,监听 127.0.0.1:8888

# 或使用 bat 脚本(初始化 DB + 启动)
start_ledger.bat

# 数据同步
python -c "from backend.sync_engine import sync_incremental; print(sync_incremental())"     # 增量同步最新消息
python -c "from backend.sync_engine import sync_full; print(sync_full('群名'))"              # 全量拉取指定群
python -c "from backend.sync_engine import sync_all_groups_full; sync_all_groups_full()"     # 全量拉取所有群
python -c "from backend.sync_engine import discover_new_groups; print(discover_new_groups())" # 发现新群

# 搜索
python -c "from backend.database import search_messages; print(search_messages('关键词'))"

# 遗留数据导入
python -m backend.import_legacy
```

## 架构

```
本地微信加密DB → [wx-cli (npm)] → sync_engine.py → SQLite + FTS5 → Flask REST API → 浏览器SPA
```

### 目录结构

```
WXDashboard/
├── backend/                 # Python 后端包
│   ├── app.py              # Flask 主应用 + 自动同步线程
│   ├── config.py           # 路径与端口配置
│   ├── database.py         # SQLite schema + FTS5 + CRUD
│   ├── sync_engine.py      # wx-cli 调用、类别推断、消息入库
│   ├── contact_extractor.py # 正则提取邮箱与手机号
│   └── import_legacy.py    # 旧版 Excel/JSON 台账导入
├── static/
│   ├── app.js              # 前端 SPA 逻辑(含自动刷新)
│   ├── style.css           # 样式(CSS 变量设计系统)
│   └── favicon.svg         # SVG 图标
├── templates/
│   └── dashboard.html      # 主页面模板
├── data/                    # SQLite 数据库(自动创建)
├── .originfiles/            # 临时/原始文件(不上传仓库)
├── requirements.txt
├── start_ledger.bat
└── .gitignore
```

### 分层

| 层       | 文件                                                                  | 职责                                                                  |
| -------- | --------------------------------------------------------------------- | --------------------------------------------------------------------- |
| 数据采集 | `backend/sync_engine.py`                                            | 通过 subprocess 调用 `wx` CLI,解析 JSON 输出,类别推断,去重入库      |
| 数据层   | `backend/database.py`                                               | SQLite schema (groups/messages/contacts/sync_log), FTS5 全文搜索,CRUD |
| Web API  | `backend/app.py`                                                    | 15 个 REST 端点,Flask 开发服务器,后台自动同步线程                     |
| 前端     | `templates/dashboard.html`, `static/app.js`, `static/style.css` | 原生 JS SPA,无框架,前端缓存 + 自动刷新                                |

### 核心依赖

- **外部工具**: `wx-cli` (npm 全局安装),需能读取本地微信 `MSG.db`
- **Python**: `flask`, `openpyxl` (参 `requirements.txt`)
- **数据库**: `data/ledger_v2.db` — SQLite WAL 模式,启用外键
- **入口**: `python -m backend.app` (或 `start_ledger.bat`)

### 数据库核心表

- `groups` — 微信群元数据(名称、类别、子类别、项目、合作方、备注)
- `messages` — 消息记录,`(group_id, local_id)` UNIQUE 去重,含 raw_json 原文
- `contacts` — 从消息中提取的邮箱/手机号,按 `(group_id, sender_name, email, phone)` 去重
- `messages_fts` — FTS5 虚拟表,索引 `group_name + sender + content`,触发器自动同步
- `sync_log` — 同步审计日志

### 群组分类体系

分类体系**随项目而定**，不是固定不变的。当前项目（工程建设项目）合作单位多，从项目管理角度按总承包和各分包分为两大类:

- **内部（总承包）**: 内部沟通、施工局合作、设计院合作
- **外部（各分包）**: 供应商询价、地基处理、建筑MEP、保险、物流

类别推断规则见 `sync_engine.py` 中的 `infer_category()`,子类别推断见 `_infer_subcategory()`。新项目启动时需根据项目特点调整分类关键词和体系。

### 前端交互要点

- 项目选择器:标题下拉切换项目,自动发现 `/api/projects`
- 左侧分类标签页:内部(上部)含 内部沟通/施工局合作/设计院合作,外部(下部)含 供应商咨询/地基处理/建筑MEP/保险
- 群组行颜色:绿色(≤3天)、琥珀色(3-7天)、红色(>7天)
- 点击行打开右侧抽屉:分页显示消息(50条/页)、自动提取的联系人信息
- 搜索面板:全库 FTS5 搜索,sender/content 范围
- 自动刷新:工具栏时钟按钮,可选 30s/1m/2m/5m 间隔,后台静默同步,有新消息自动更新表格

### API 端点一览

| 方法 | 路径                                 | 说明                                 |
| ---- | ------------------------------------ | ------------------------------------ |
| GET  | `/api/groups`                      | 群组列表(支持 category/project 筛选) |
| GET  | `/api/groups/<id>`                 | 群组详情                             |
| GET  | `/api/groups/<id>/messages`        | 分页消息(limit/offset)               |
| GET  | `/api/groups/<id>/messages/latest` | 最近 N 条消息                        |
| GET  | `/api/groups/<id>/contacts`        | 群组联系人                           |
| POST | `/api/groups/<id>/subcategory`     | 设置子类别                           |
| GET  | `/api/categories`                  | 分类列表                             |
| GET  | `/api/search`                      | FTS5 全文搜索                        |
| GET  | `/api/projects`                    | 项目列表                             |
| GET  | `/api/sync/status`                 | 同步统计                             |
| POST | `/api/sync/refresh`                | 增量同步                             |
| POST | `/api/sync/pull-all`               | 全量拉取(可指定群)                   |
| POST | `/api/sync/discover`               | 发现新群组                           |
| POST | `/api/sync/auto/start`             | 启动自动同步(参数 interval 秒)       |
| POST | `/api/sync/auto/stop`              | 停止自动同步                         |
| GET  | `/api/sync/auto/status`            | 自动同步状态                         |

### 关键路径/常量

- 数据库: `data/ledger_v2.db` (由 `init_db()` 自动创建)
- 临时文件: `.originfiles/` (已加入 .gitignore)
- AI 产出归档: `.originfiles/AIWork/` (摘要、提取结果 Markdown 备份)

## AI 辅助操作

Claude Code 对本项目的 AI 介入定位:**信息筛选与整理**，让微信群工作信息更清晰展示。不涉及比价、问答、语义搜索、风险预警。所有 AI 处理均在 Claude Code 会话中完成，不接入外部 API。

### 群组智能分类

分类体系随项目而定。当有未分类或分类存疑的群时:

1. 查询 `SELECT name FROM groups WHERE category IS NULL OR category = ''`
2. 取群名 + 该群最近 5 条消息 (`SELECT content, sender FROM messages WHERE group_id=? ORDER BY timestamp DESC LIMIT 5`)
3. 根据当前项目特点判断分类。先了解项目合作方构成，再参照现有分类体系推断。工程项目的典型分类模式:总承包（内部沟通、施工局合作、设计院合作）、各分包（供应商询价、地基处理、建筑MEP、保险、物流）
4. 通过 `/api/groups/<id>/subcategory` 写入 `category` 和 `sub_category`
5. 如判断不确定，标记为"待确认"并给出理由，不强行分类

### 群聊摘要生成

使用 `baoyu-wechat-summary` 技能对指定群、指定时段生成摘要。**仅对消息数 > 50 条的群执行摘要**，消息太少的群没有摘要价值。

1. 先查询: `SELECT id, name, msg_count FROM groups WHERE msg_count > 50 ORDER BY msg_count DESC`
2. 调用 `Skill` 工具，skill="baoyu-wechat-summary"，传入群名和时间范围
3. 技能会自动从 `messages` 表读取目标消息并生成结构化摘要
4. 摘要写入 `ai_summaries` 表（group_id, date_range, summary_text, key_topics, generated_at）
5. 同时备份 Markdown 到 `.originfiles/AIWork/summaries/<群名>_<日期>.md`
6. 前端群详情页"群摘要"标签页展示

### 关键信息提取

按需从群消息中提取结构化信息:

1. 从 `messages` 表读取目标群、目标时段消息
2. 按以下维度提取:
   - 联系人信息（公司名、职位、联系方式）
   - 技术参数（规格、标准、指标值）
   - 工期节点（计划日期、里程碑事件）
   - 文件/图纸引用（编号、版本、发布日期）
3. 提取结果写入 `ai_extractions` 表（message_id 可选, extract_type, content JSON）
4. 同时备份 Markdown 到 `.originfiles/AIWork/extractions/<群名>_<日期>.md`
5. 前端群详情页"关键信息"标签页展示

### AI 产出物存放

数据库为主存储，Markdown 为备份:

| 类型 | 数据库表 | Markdown 备份 |
|------|---------|--------------|
| 摘要 | `ai_summaries` (group_id, date_range, summary_text, key_topics JSON, generated_at) | `.originfiles/AIWork/summaries/<群名>_<日期>.md` |
| 信息提取 | `ai_extractions` (group_id, message_id, extract_type, content JSON) | `.originfiles/AIWork/extractions/<群名>_<日期>.md` |

### 前端 AI 功能

群消息详情抽屉右侧增加两个标签页:
- **群摘要**: 展示该群的 AI 摘要列表，按时间倒序
- **关键信息**: 分类展示提取的结构化信息（联系人、技术参数、工期、文件）

后端需新增对应 API: `GET /api/groups/<id>/summaries` 和 `GET /api/groups/<id>/extractions`

## 项目改造背景

当前项目是方案一(Flask+SQLite)的落地实现。改造目标是将静态 HTML/JSON 台账(原方案)升级为支持动态刷新、分类筛选、全文检索的交互式 Web 应用。后续计划通过 Claude Code 对消息进行 AI 摘要和信息提取。
