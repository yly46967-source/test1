# AInsight - AI 情报聚合器

> 一个面向 AI 从业者的轻量级情报聚合工具
>
> 核心理念：**RSS 万物皆可订阅 + AI 智能合成 = 高密度情报**

---

## 1. 项目定位

### 一句话描述
**AInsight = RSSHub 数据源 + 主题聚类 + AI 情报合成 + Telegram 推送**

### 目标用户
- AI 开发者：追踪技术动态、开源项目
- AI 投资人：追踪融资、市场信号
- AI 创业者：追踪竞品、行业趋势

### 核心价值
| 痛点 | 解决方案 |
|------|----------|
| X/GitHub 信息分散 | RSSHub 统一订阅 |
| 信息过载 | AI 主题聚类 |
| 缺乏深度分析 | AI 情报合成 |
| 需要主动刷信息 | Telegram 定时推送 |

---

## 2. 技术架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        AInsight 架构                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   数据源层（RSSHub 路由）                                         │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│   │ X/推特   │ │ GitHub   │ │ 科技媒体 │ │ 论文站   │          │
│   │ KOL 推文 │ │ Trending │ │ TC/HN    │ │ arXiv    │          │
│   └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘          │
│        │            │            │            │                  │
│        └────────────┴────────────┴────────────┘                  │
│                          │                                       │
│                          ▼                                       │
│   ┌─────────────────────────────────────────┐                   │
│   │         RSS 抓取器 (已有)                │                   │
│   │   • 并发抓取 • 自动重试 • 去重          │                   │
│   └─────────────────────────────────────────┘                   │
│                          │                                       │
│                          ▼                                       │
│   ┌─────────────────────────────────────────┐                   │
│   │         主题聚类器 (已有)                │                   │
│   │   • FTS 快速匹配 • LLM 精确判断         │                   │
│   └─────────────────────────────────────────┘                   │
│                          │                                       │
│                          ▼                                       │
│   ┌─────────────────────────────────────────┐                   │
│   │         情报合成引擎 (已有)              │                   │
│   │   • TLDR • 行动指南 • 逻辑推演          │                   │
│   └─────────────────────────────────────────┘                   │
│                          │                                       │
│                          ▼                                       │
│   ┌─────────────────────────────────────────┐                   │
│   │         输出层                           │                   │
│   │   • Telegram Bot (已有)                 │                   │
│   │   • Web UI (P2)                         │                   │
│   └─────────────────────────────────────────┘                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 已完成模块

| 模块 | 状态 | 文件 |
|------|------|------|
| RSS 抓取器 | ✅ 完成 | `src/fetcher/rss.py` |
| 并发抓取 | ✅ 完成 | `src/utils.py` |
| AI 总结/分类 | ✅ 完成 | `src/processor/` |
| Telegram 推送 | ✅ 完成 | `src/notifier/telegram.py` |
| 数据库模型 | ✅ 完成 | `src/database/models.py` |
| 主题聚类器 | ✅ 完成 | `src/clustering/topic_cluster.py` |
| 聚类流水线 | ✅ 完成 | `src/clustering/pipeline.py` |
| 情报合成引擎 | ✅ 完成 | `src/processor/synthesis.py` |
| 日志系统 | ✅ 完成 | `src/logger.py` |

---

## 4. 待完成任务

### Phase 1: 数据源扩展（本周）

**目标：接入 RSSHub，获取 X/GitHub 数据**

| 任务 | 优先级 | 说明 |
|------|--------|------|
| 扩展 sources.yaml | P0 | 添加 RSSHub 路由配置 |
| 添加 KOL 配置 | P0 | 配置要追踪的 AI KOL |
| 适配 RSSHub 格式 | P0 | 解析 X 推文、GitHub 动态 |

**RSSHub 路由示例：**
```yaml
# X/Twitter KOL
- name: "Karpathy"
  url: "https://rsshub.app/twitter/user/karpathy"
  type: "x_kol"
  kol_tier: "god"

# GitHub Trending
- name: "GitHub AI Trending"
  url: "https://rsshub.app/github/trending/daily/python?since=daily"
  type: "github"
```

### Phase 2: 流程串联（下周）

**目标：打通 抓取 → 聚类 → 合成 → 推送 全流程**

| 任务 | 优先级 | 说明 |
|------|--------|------|
| 集成聚类到主流程 | P0 | main.py 调用聚类流水线 |
| 集成合成到主流程 | P0 | 触发条件：≥3 条来源 |
| 情报推送格式 | P1 | Telegram 展示情报包 |

### Phase 3: 优化迭代（后续）

| 任务 | 优先级 | 说明 |
|------|--------|------|
| Web UI | P2 | 简单的情报浏览页面 |
| 订阅管理 | P2 | 用户自定义订阅 |
| 历史回溯 | P2 | 情报时间线 |

---

## 5. 数据流示例

```
1. 抓取阶段
   RSSHub/twitter/user/karpathy → RSS 抓取器 → RawContent 表

2. 聚类阶段
   RawContent → FTS 匹配 → LLM 判断 → Topic 表

3. 合成阶段（≥3 条来源触发）
   Topic + RawContents → 合成引擎 → IntelligencePackage 表

4. 推送阶段
   IntelligencePackage → Telegram Bot → 用户
```

---

## 6. 配置示例

### sources.yaml 新增结构

```yaml
# AI KOL 追踪（通过 RSSHub）
ai_kols:
  - handle: "karpathy"
    name: "Andrej Karpathy"
    tier: "god"
    rsshub_route: "/twitter/user/karpathy"

  - handle: "ylecun"
    name: "Yann LeCun"
    tier: "god"
    rsshub_route: "/twitter/user/ylecun"

  - handle: "jimfan"
    name: "Jim Fan"
    tier: "expert"
    rsshub_route: "/twitter/user/DrJimFan"

# AI 关键词追踪
ai_keywords:
  - keyword: "GPT-5"
    rsshub_route: "/twitter/search/GPT-5"

  - keyword: "Claude"
    rsshub_route: "/twitter/search/Claude%20AI"

# GitHub 追踪
github:
  - name: "AI Trending"
    rsshub_route: "/github/trending/daily/python"

  - name: "LangChain"
    rsshub_route: "/github/repos/langchain-ai/langchain"

# RSSHub 实例配置
rsshub:
  base_url: "https://rsshub.app"  # 公共实例或自部署
  # base_url: "http://localhost:1200"  # 自部署
```

---

## 7. 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 API Key

# 3. 初始化数据库
python scripts/init_db.py

# 4. 测试运行
python main.py --test

# 5. 定时运行
python main.py --schedule
```

---

## 8. 项目原则

1. **MVP 优先**：先跑起来，再优化
2. **复用优先**：最大化利用已有代码
3. **简单优先**：不过度设计，够用就行
4. **数据优先**：先有数据，再做分析

---

## 9. 里程碑

| 里程碑 | 目标 | 状态 |
|--------|------|------|
| M1 | RSS 抓取 + AI 总结 + Telegram 推送 | ✅ 完成 |
| M2 | RSSHub 数据源 + 主题聚类 | 🚧 进行中 |
| M3 | 情报合成 + 智能推送 | ⏳ 待开始 |
| M4 | Web UI + 订阅管理 | ⏳ 待开始 |

---

## 10. 文件结构

```
news-funnel/
├── main.py                      # 主程序入口
├── requirements.txt
├── .env
├── config/
│   └── sources.yaml             # 数据源配置（扩展中）
├── docs/
│   ├── PRODUCT_PLAN.md          # 本文件
│   ├── PROJECT_STATUS.md        # 项目状态
│   ├── SCHEMA_DESIGN.md         # 数据结构设计
│   ├── PROMPT_PROTOCOL.md       # Prompt 协议
│   └── CLUSTERING_ARCHITECTURE.md
├── src/
│   ├── database/
│   │   ├── models.py            # ORM 模型（已扩展）
│   │   └── service.py           # 数据库服务（已扩展）
│   ├── fetcher/
│   │   ├── base.py
│   │   └── rss.py               # RSS 抓取器
│   ├── clustering/              # 聚类模块（新增）
│   │   ├── topic_cluster.py
│   │   └── pipeline.py
│   ├── processor/
│   │   ├── summarizer.py
│   │   ├── classifier.py
│   │   ├── synthesis.py         # 情报合成（新增）
│   │   └── synthesis_service.py
│   ├── notifier/
│   │   └── telegram.py
│   ├── logger.py
│   └── utils.py
└── scripts/
    ├── init_db.py
    └── test_db.py
```
