# News Funnel 📰

一个自动化新闻聚合系统，从多个 RSS 源抓取新闻，通过 AI 进行智能总结和分类，并推送到 Telegram。

## 功能特性

- 🔄 **多源聚合** - 支持 14+ 个新闻源（BBC、CNN、NYT、中国日报等）
- 🤖 **AI 处理** - 使用阿里云 Qwen Plus 模型进行新闻总结和分类
- 📱 **Telegram 推送** - 自动推送新闻摘要到 Telegram
- ⏰ **定时任务** - 支持早/午/晚报自动推送
- 🏷️ **智能分类** - 8 大类别（科技、政治、经济、社会、国际、体育、娱乐、其他）
- 🗄️ **数据持久化** - PostgreSQL/SQLite 数据库支持，自动去重

## 项目结构

```
news-funnel/
├── main.py                 # 主程序入口
├── requirements.txt        # Python 依赖
├── .env                    # 环境变量配置
├── config/
│   └── sources.yaml        # 新闻源配置
├── scripts/
│   └── init_db.py          # 数据库初始化脚本
└── src/
    ├── models.py           # 数据模型
    ├── database/           # 数据库模块
    │   ├── models.py       # ORM 模型
    │   └── service.py      # 数据库服务层
    ├── fetcher/            # 新闻抓取模块
    │   ├── base.py         # 抓取器基类
    │   └── rss.py          # RSS 抓取器
    ├── processor/          # AI 处理模块
    │   ├── summarizer.py   # 新闻总结
    │   └── classifier.py   # 新闻分类
    └── notifier/           # 通知模块
        └── telegram.py     # Telegram 推送
```

## 技术栈

- **Python 3.10+**
- **SQLAlchemy 2.0** - ORM 框架
- **PostgreSQL** - 生产数据库（阿里云 RDS）
- **SQLite** - 开发数据库
- **asyncpg** - PostgreSQL 异步驱动
- **feedparser** - RSS 解析
- **httpx** - 异步 HTTP 客户端
- **openai** - DashScope API 客户端
- **python-telegram-bot** - Telegram Bot API
- **apscheduler** - 定时任务调度

## 数据库设计

### ER 图

```
┌─────────────────┐       ┌─────────────────┐
│  news_sources   │       │     users       │
├─────────────────┤       ├─────────────────┤
│ id              │       │ id              │
│ name            │       │ username        │
│ url             │       │ email           │
│ region          │       │ password_hash   │
│ source_type     │       │ telegram_chat_id│
│ enabled         │       │ is_admin        │
│ fetch_interval  │       └────────┬────────┘
│ last_fetch_at   │                │
└────────┬────────┘                │
         │                         │
         │ 1:N                     │ 1:1
         ▼                         ▼
┌─────────────────┐       ┌─────────────────┐
│ news_articles   │       │user_subscriptions│
├─────────────────┤       ├─────────────────┤
│ id              │       │ id              │
│ title           │       │ user_id         │
│ url             │       │ categories      │
│ url_hash (唯一) │       │ regions         │
│ content         │       │ sources         │
│ summary         │       │ push_enabled    │
│ category        │       │ push_times      │
│ region          │       └─────────────────┘
│ source_id (FK)  │
│ is_processed    │
│ is_sent         │
│ published_at    │
└────────┬────────┘
         │
         │ N:1
         ▼
┌─────────────────┐
│   fetch_logs    │
├─────────────────┤
│ id              │
│ source_id (FK)  │
│ status          │
│ items_fetched   │
│ items_new       │
│ error_message   │
│ duration_ms     │
└─────────────────┘
```

### 核心表说明

| 表名 | 说明 |
|------|------|
| `news_sources` | 新闻源配置，支持动态管理 |
| `news_articles` | 新闻文章，通过 url_hash 去重 |
| `fetch_logs` | 抓取日志，记录每次抓取结果 |
| `users` | 用户表（WebUI 预留） |
| `user_subscriptions` | 用户订阅配置（WebUI 预留） |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填入你的配置：

```env
# DashScope API
DASHSCOPE_API_KEY=your_api_key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-plus

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Database
# 开发环境 (SQLite)
DATABASE_URL=sqlite+aiosqlite:///./news_funnel.db

# 生产环境 (PostgreSQL - 阿里云 RDS)
# DATABASE_URL=postgresql+asyncpg://user:password@host:5432/news_funnel
```

### 3. 初始化数据库

```bash
python scripts/init_db.py
```

这将：
- 创建所有数据库表
- 将 `config/sources.yaml` 中的新闻源同步到数据库

### 4. 运行

```bash
# 单次运行
python main.py

# 测试模式（只处理 3 条新闻）
python main.py --test

# 跳过 AI 处理
python main.py --skip-ai

# 跳过 Telegram 推送
python main.py --skip-telegram

# 启动定时任务模式
python main.py --schedule
```

## 定时任务

启用 `--schedule` 后，系统将在以下时间自动推送（北京时间）：

| 时间 | 说明 |
|------|------|
| 08:00 | 早报 |
| 12:00 | 午报 |
| 21:00 | 晚报 |

## 新闻源配置

编辑 `config/sources.yaml` 添加或修改新闻源：

```yaml
sources:
  - name: "BBC World"
    url: "https://feeds.bbci.co.uk/news/world/rss.xml"
    region: "world"
    type: "rss"
    enabled: true
```

## 新闻分类

系统支持 8 种新闻分类：

- 🔬 科技 (Technology)
- 🏛️ 政治 (Politics)
- 💰 经济 (Economy)
- 👥 社会 (Society)
- 🌍 国际 (International)
- ⚽ 体育 (Sports)
- 🎬 娱乐 (Entertainment)
- 📌 其他 (Other)

## 数据流

```
                    ┌─────────────┐
                    │  RSS 源     │
                    └──────┬──────┘
                           │
                           ▼
┌──────────────────────────────────────────┐
│              Fetcher 模块                │
│  - 抓取新闻                              │
│  - URL 去重 (数据库)                     │
│  - 保存到 news_articles                  │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│             Processor 模块               │
│  - AI 总结 (Qwen Plus)                   │
│  - AI 分类                               │
│  - 更新 is_processed                     │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│             Notifier 模块                │
│  - 推送到 Telegram                       │
│  - 更新 is_sent                          │
└──────────────────────────────────────────┘
```

## 部署到阿里云

### 推荐配置

- **ECS**: 1 核 2G 即可
- **RDS PostgreSQL**: 基础版
- **定时任务**: 使用 systemd 或 cron

### PostgreSQL 连接配置

```env
DATABASE_URL=postgresql+asyncpg://username:password@rm-xxx.pg.rds.aliyuncs.com:5432/news_funnel
```

## 未来规划

- [ ] WebUI 管理界面
- [ ] 用户注册/登录
- [ ] 个性化订阅
- [ ] 更多新闻源类型（API、网页爬虫）
- [ ] 新闻搜索功能
- [ ] 数据统计分析

## License

MIT
