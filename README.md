# AInsight - AI 情报聚合系统

从 Twitter/X KOL、RSS 等多源抓取 AI 领域资讯，通过 AI 聚类分析生成情报洞察。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 3. 初始化数据库
python scripts/init_db.py

# 4. 启动 Web UI
python run_web.py
# 访问 http://localhost:8001

# 5. 运行抓取 + 聚类 + 情报生成
python ainsight.py
```

## 项目架构

```
news-funnel/
├── src/
│   ├── database/           # 数据库层
│   │   ├── models.py       # ORM 模型 (Topic, RawContent, Intelligence, KOL)
│   │   └── service.py      # 数据库服务
│   ├── fetcher/            # 数据抓取
│   │   ├── nitter_gateway.py   # Nitter RSS 网关 (抓取 Twitter)
│   │   ├── twitter_fetcher.py  # Twitter 抓取器
│   │   └── rss.py              # RSS 抓取器
│   ├── clustering/         # 聚类分析
│   │   ├── deduplicator.py     # 内容去重 (SimHash)
│   │   ├── topic_cluster.py    # 主题聚类 (Embedding + DBSCAN)
│   │   ├── content_scorer.py   # 内容评分
│   │   └── enhanced_pipeline.py # 完整聚类流水线
│   ├── processor/          # AI 处理
│   │   ├── enhanced_synthesis.py # 情报生成 (Qwen)
│   │   └── classifier.py       # 分类器
│   ├── web/                # Web UI
│   │   ├── app.py              # FastAPI 应用
│   │   ├── templates/          # Jinja2 模板
│   │   └── static/             # 静态资源 (CSS, JS, i18n)
│   └── notifier/           # 通知推送
│       └── telegram.py
├── config/
│   └── sources.yaml        # RSS 源配置
├── ainsight.py             # 主程序入口
├── run_web.py              # Web 服务启动
└── main.py                 # 旧版入口 (兼容)
```

## 核心数据模型

```
KOL (Twitter 博主)
 └── RawContent (原始内容)
       └── Topic (聚类主题)
             └── Intelligence (情报洞察)
```

| 模型 | 说明 |
|------|------|
| `KOL` | Twitter 博主，含 tier(等级)、category(分类)、weight(权重) |
| `RawContent` | 抓取的原始内容，含 content_hash 去重 |
| `Topic` | 聚类后的主题，多条 RawContent 聚合为一个 Topic |
| `Intelligence` | AI 生成的情报洞察，含 tldr、verdict、keywords |

## 主要功能模块

### 1. KOL 管理 (`/kols`)
- 批量导入 Twitter handle
- 分级管理 (God/Expert/Insider/Observer)
- 分类标签 (研究员/创始人/投资人/工程师/媒体/博主)

### 2. 内容抓取 (`src/fetcher/`)
- **Nitter 网关**: 通过 Nitter 实例抓取 Twitter RSS
- **去重机制**: SimHash 相似度检测，避免重复入库

### 3. 聚类分析 (`src/clustering/`)
- **Embedding**: 使用 DashScope text-embedding-v3 生成向量
- **聚类算法**: DBSCAN 基于密度聚类
- **主题生成**: AI 生成主题标题和分类

### 4. 情报生成 (`src/processor/enhanced_synthesis.py`)
- 当主题关联 3+ 条原文时自动生成
- 输出: tldr(一句话总结)、verdict(结论)、keywords(关键词)

### 5. Web UI (`src/web/`)
- 首页: 今日情报列表 + 详情面板
- KOL 管理页: 增删改查 + 批量导入
- 多语言: i18next 支持中英切换

## 环境变量 (.env)

```env
# 数据库
DATABASE_URL=sqlite+aiosqlite:///./ainsight.db

# DashScope (阿里云 AI)
DASHSCOPE_API_KEY=sk-xxx
DASHSCOPE_MODEL=qwen-plus

# Telegram 推送 (可选)
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
```

## 常用命令

```bash
# 完整流程: 抓取 → 去重 → 聚类 → 情报生成
python ainsight.py

# 仅抓取 KOL 内容
python ainsight.py --fetch-only

# 仅运行聚类
python ainsight.py --cluster-only

# 启动 Web UI (开发模式，自动重载)
python run_web.py
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 首页 |
| `/kols` | GET | KOL 管理页 |
| `/api/kols` | POST | 添加 KOL |
| `/api/kols/batch` | POST | 批量导入 KOL |
| `/api/kols/{id}` | PUT/DELETE | 更新/删除 KOL |
| `/api/topic/{id}` | GET | 获取主题详情 |
| `/api/translate` | POST | 翻译文本 (Google Translate) |

## 技术栈

- **后端**: FastAPI + SQLAlchemy 2.0 + asyncio
- **前端**: Jinja2 + Vanilla JS + i18next
- **AI**: 阿里云 DashScope (Qwen-Plus, text-embedding-v3)
- **数据库**: SQLite (开发) / PostgreSQL (生产)

## 开发注意事项

1. **翻译 API**: 需重启服务器才能生效 (`python run_web.py`)
2. **Nitter 实例**: 默认使用 `nitter.privacydev.net`，可在代码中修改
3. **聚类参数**: `eps=0.3, min_samples=2`，可在 `topic_cluster.py` 调整
