# AInsight - AI 情报聚合器

从 Twitter/X KOL 抓取 AI 行业动态，通过 AI 聚类和合成生成高密度情报摘要。

## 功能特点

- **Chrome Profile 登录抓取**：使用已登录的 Chrome 浏览器 Cookie，无需 API Key
- **FxTwitter API**：获取完整推文数据（包括互动数据、媒体等）
- **智能过滤**：规则过滤 + 价值评分，自动过滤低质量内容
- **主题提取**：LLM 自动提取推文主题
- **情报合成**：多源信息聚合，生成结构化情报包
- **X 风格 UI**：简洁的三栏布局，热度排行 + 今日情报

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置 Cookie

首先在 Chrome 中登录 X (x.com)，然后导出 Cookie：

```bash
python scripts/export_x_cookies.py
```

按提示输入 `auth_token` 和 `ct0`（从 Chrome DevTools → Application → Cookies 获取）。

### 3. 导入 KOL

方式一：从关注列表导入（推荐）

```bash
python scripts/import_following_as_kols.py
```

方式二：手动配置 `config/kols.yaml`

### 4. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```env
# 数据库
DATABASE_URL=sqlite+aiosqlite:///./ainsight_v3.db

# 阿里云 DashScope (必填，用于主题提取和情报合成)
DASHSCOPE_API_KEY=sk-xxx
DASHSCOPE_MODEL=qwen-plus

# Telegram 推送 (可选)
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
```

### 5. 运行

```bash
# 运行完整流程（抓取→过滤→主题提取→情报生成）+ Web 服务
python ainsight.py --all

# 仅运行抓取流程
python ainsight.py

# 仅启动 Web 服务
python ainsight.py --web
```

访问 <http://localhost:8001> 查看结果。

## 命令说明

| 命令 | 说明 |
|------|------|
| `python ainsight.py` | 运行完整流程 |
| `python ainsight.py --web` | 仅启动 Web 服务 (http://localhost:8001) |
| `python ainsight.py --all` | 同时运行流程和 Web |
| `python ainsight.py --init` | 初始化数据库 |
| `python ainsight.py --limit 20` | 限制抓取 KOL 数量（默认 10） |
| `python ainsight.py --profile "Default"` | 指定 Chrome Profile |
| `python ainsight.py --list-profiles` | 列出可用的 Chrome Profile |

## 数据流程

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   抓取      │ ──▶ │   过滤      │ ──▶ │  主题提取   │ ──▶ │  情报生成   │
│ Chrome+FxAPI│     │ 规则+评分   │     │   LLM      │     │   LLM      │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      │                   │                   │                   │
      ▼                   ▼                   ▼                   ▼
  RawContent          过滤垃圾           topic_name        IntelligencePackage
  (原始推文)          低质量内容         (主题标签)          (AI 合成情报)
```

## 项目结构

```
ainsight/
├── ainsight.py              # 主程序入口
├── requirements.txt         # 依赖
├── .env                     # 环境变量
├── config/
│   ├── kols.yaml           # KOL 配置（可选）
│   └── x_cookies.json      # X Cookie（自动生成）
├── scripts/
│   ├── export_x_cookies.py      # 导出 Cookie 工具
│   └── import_following_as_kols.py  # 从关注列表导入 KOL
├── src/
│   ├── database/
│   │   ├── models.py       # 数据库模型
│   │   └── service.py      # 数据库服务
│   ├── fetcher/
│   │   └── chrome_twitter.py    # Chrome + FxTwitter 抓取
│   ├── algorithms/
│   │   ├── scoring.py      # 价值评分
│   │   ├── topic.py        # 主题提取
│   │   └── intel.py        # 情报生成
│   └── web/
│       ├── app.py          # FastAPI 应用
│       ├── templates/      # Jinja2 模板
│       └── static/         # 静态资源 (CSS)
└── logs/
    └── news_funnel.log     # 日志文件
```

## Web 界面

### 首页（三栏布局）

- **左栏**：导航菜单（首页、KOL 管理、设置等）
- **中栏**：热度排行（按价值评分排序的推文列表）
- **右栏**：今日情报（AI 合成的情报摘要）

### KOL 管理

- 查看所有 KOL（支持分页）
- 添加/编辑/删除 KOL
- 批量导入 KOL
- 显示 KOL 头像（抓取后自动获取）

## API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 首页 |
| GET | `/kols` | KOL 管理页面 |
| GET | `/api/stats` | 统计数据 |
| GET | `/api/kols` | KOL 列表 |
| POST | `/api/kols` | 创建 KOL |
| PUT | `/api/kols/{id}` | 更新 KOL |
| DELETE | `/api/kols/{id}` | 删除 KOL |
| GET | `/api/content/{id}` | 内容详情 |

## 技术栈

- **后端**: FastAPI, SQLAlchemy 2.0, asyncio
- **数据库**: SQLite (aiosqlite)
- **抓取**: Playwright + FxTwitter API
- **LLM**: 阿里云 DashScope (Qwen-Plus)
- **前端**: Jinja2 模板, 原生 CSS (X 风格)

## 情报输出格式

每个情报包包含：

- **tldr**: 一句话总结
- **signal**: 核心信号（关键信息点）
- **shift**: 利益重构（对各方的影响）
- **alpha**: 行动灵感（可执行的建议）

## 注意事项

1. **Cookie 有效期**：X Cookie 可能会过期，需要定期更新
2. **抓取频率**：建议每次抓取间隔 3 秒以上，避免被限制
3. **LLM 成本**：主题提取和情报生成会消耗 API 调用

## License

MIT
