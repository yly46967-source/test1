# AInsight 项目状态

> 更新时间: 2024-02-19
> 当前阶段: Phase 2 - 流程验证 ✅ 完成

---

## 项目定位

**AInsight** = RSSHub 数据源 + 主题聚类 + AI 情报合成 + Telegram 推送

一个面向 AI 从业者的轻量级情报聚合工具，对标 Follow (Folo)，但更简洁。

### 核心理念
- **RSS 万物皆可订阅**：通过 RSSHub 统一获取 X/GitHub/媒体数据
- **AI 智能合成**：多源聚类 + 情报合成，输出高密度信息
- **被动接收**：Telegram 定时推送，无需主动刷信息

---

## 当前进度

### ✅ 已完成 (P0)

| 模块 | 文件 | 说明 |
|------|------|------|
| RSS 抓取器 | `src/fetcher/rss.py` | 并发抓取、自动重试、去重 |
| **AInsight 抓取器** | `src/fetcher/ainsight_fetcher.py` | **统一抓取器，支持 RSSHub** |
| **数据源加载器** | `src/fetcher/source_loader.py` | **新配置格式解析** |
| AI 处理 | `src/processor/summarizer.py` | Qwen Plus 总结 |
| AI 分类 | `src/processor/classifier.py` | 8 大分类 |
| Telegram 推送 | `src/notifier/telegram.py` | 自动分页、按分类分组 |
| 数据库模型 | `src/database/models.py` | **11 张表，含 FTS 索引** |
| 数据库服务 | `src/database/service.py` | 完整 CRUD + 聚类操作 |
| **主题聚类器** | `src/clustering/topic_cluster.py` | **FTS + LLM 两阶段聚类** |
| **聚类流水线** | `src/clustering/pipeline.py` | **完整处理流程** |
| **情报合成引擎** | `src/processor/synthesis.py` | **多源合成情报包** |
| **合成服务** | `src/processor/synthesis_service.py` | **数据库集成** |
| **AInsight 主程序** | `ainsight.py` | **完整流程入口** |
| 日志系统 | `src/logger.py` | 彩色输出、文件轮转 |

### ✅ Phase 1 & 2 完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 扩展 sources.yaml | ✅ | RSSHub 路由配置 |
| KOL 配置 | ✅ | AI 领域 KOL 列表 |
| RSSHub 格式适配 | ✅ | 统一抓取器 |
| 集成聚类到主流程 | ✅ | ainsight.py |
| 集成合成到主流程 | ✅ | ≥3 来源触发 |
| 端到端测试 | ✅ | 完整流程跑通 |
| Telegram 格式优化 | ✅ | 情报推送、每日摘要 |

### ⏳ 待开始 (Phase 3)

| 任务 | 说明 |
|------|------|
| 自部署 RSSHub | 启用 X/Twitter 和 GitHub 数据源 |
| Web UI | 简单的情报浏览页面 |
| 订阅管理 | 用户自定义订阅 |

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        AInsight 架构                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   数据源层（RSSHub）                                             │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│   │ X KOL    │ │ GitHub   │ │ 科技媒体 │ │ 论文站   │          │
│   └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘          │
│        └────────────┴────────────┴────────────┘                  │
│                          │                                       │
│                          ▼                                       │
│   ┌─────────────────────────────────────────┐                   │
│   │         AInsight 抓取器 ✅               │                   │
│   │   • 统一接口 • 并发抓取 • 自动重试       │                   │
│   └─────────────────────────────────────────┘                   │
│                          │                                       │
│                          ▼                                       │
│   ┌─────────────────────────────────────────┐                   │
│   │         主题聚类器 ✅                    │                   │
│   │   FTS 快速匹配 → LLM 精确判断           │                   │
│   └─────────────────────────────────────────┘                   │
│                          │                                       │
│                          ▼                                       │
│   ┌─────────────────────────────────────────┐                   │
│   │         情报合成引擎 ✅                  │                   │
│   │   ≥3 来源触发 → TLDR/行动指南/推演      │                   │
│   └─────────────────────────────────────────┘                   │
│                          │                                       │
│                          ▼                                       │
│   ┌─────────────────────────────────────────┐                   │
│   │         Telegram 推送 ✅                 │                   │
│   └─────────────────────────────────────────┘                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 数据源配置

### 已配置数据源（19 个）

| 类型 | 数量 | 示例 |
|------|------|------|
| X KOL | 7 | Karpathy, LeCun, Sam Altman, Jim Fan... |
| X 关键词 | 3 | GPT-5, Claude 4, Gemini 2 |
| GitHub | 5 | AI Trending, LangChain, Ollama... |
| 科技媒体 | 4 | TechCrunch, Hacker News, The Verge... |

### KOL 等级

| 等级 | 说明 | 示例 |
|------|------|------|
| god | 行业领袖 | Karpathy, LeCun, Sam Altman |
| expert | 技术专家 | Jim Fan, Swyx |
| insider | 业内人士 | Bindu Reddy |
| observer | 观察者 | 其他 |

---

## 运行命令

```bash
# 测试运行（跳过 AI 和推送）
python ainsight.py --test --skip-clustering --skip-synthesis --skip-telegram

# 完整运行
python ainsight.py --test

# 定时运行（8:00/12:00/21:00）
python ainsight.py --schedule

# 查看帮助
python ainsight.py --help

# 旧版本（仍可用）
python main.py --test
```

---

## 关键配置

### .env 环境变量
```
DASHSCOPE_API_KEY=xxx      # 阿里云 Qwen API
TELEGRAM_BOT_TOKEN=xxx     # Telegram Bot
TELEGRAM_CHAT_ID=xxx       # 推送目标
DATABASE_URL=sqlite+aiosqlite:///./ainsight.db
LLM_MODEL=qwen-plus        # 可选，默认 qwen-plus
```

### RSSHub 实例
```bash
# 公共实例（有限流）
https://rsshub.app

# 自部署（推荐）
docker run -d -p 1200:1200 diygod/rsshub
```

---

## 文件结构

```
news-funnel/
├── ainsight.py                  # AInsight 主程序入口 ✅
├── main.py                      # 旧版主程序（保留）
├── config/
│   └── sources.yaml             # 数据源配置 ✅
├── docs/
│   ├── PRODUCT_PLAN.md          # 产品计划书
│   ├── PROJECT_STATUS.md        # 本文件
│   └── ...
├── src/
│   ├── database/
│   │   ├── models.py            # ORM 模型（11 张表）
│   │   └── service.py           # 数据库服务
│   ├── fetcher/
│   │   ├── ainsight_fetcher.py  # AInsight 抓取器 ✅
│   │   ├── source_loader.py     # 配置加载器 ✅
│   │   └── rss.py               # RSS 抓取器
│   ├── clustering/              # 聚类模块 ✅
│   │   ├── topic_cluster.py
│   │   └── pipeline.py
│   ├── processor/
│   │   ├── synthesis.py         # 情报合成 ✅
│   │   └── synthesis_service.py
│   ├── notifier/
│   │   └── telegram.py
│   └── logger.py
└── scripts/
    └── init_db.py
```

---

## 下一步行动

### 启动 RSSHub（启用 X/Twitter 和 GitHub）

```bash
# 方式 1: 使用 Docker Compose（推荐）
docker-compose up -d rsshub

# 方式 2: 直接运行
docker run -d -p 1200:1200 diygod/rsshub

# 切换到本地 RSSHub 并启用所有数据源
python scripts/switch_rsshub.py local

# 测试
python ainsight.py --test --skip-telegram
```

### Phase 3 待完成

| 任务 | 说明 |
|------|------|
| Web UI | 简单的情报浏览页面（可选） |
| 订阅管理 | 用户自定义数据源（可选） |

---

## 新窗口快速开始

复制以下指令到新对话：

> 请阅读 `docs/PROJECT_STATUS.md` 了解项目状态。项目已完成 Phase 2，可以运行 `python ainsight.py --test --skip-telegram` 测试完整流程。如需启用 X/Twitter 数据源，运行 `docker-compose up -d rsshub` 然后 `python scripts/switch_rsshub.py local`。
