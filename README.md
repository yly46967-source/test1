# AInsight - AI 情报聚合器

从 Twitter/X KOL 抓取 AI 行业动态，通过 AI 聚类和合成生成高密度情报摘要。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt
playwright install chromium

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 初始化数据库
python ainsight.py --init

# 运行完整流程（抓取→过滤→聚类→合成）
python ainsight.py

# 启��� Web 界面
python ainsight.py --web

# 同时运行流程和 Web（推荐）
python ainsight.py --all
```

## 命令说明

| 命令 | 说明 |
|------|------|
| `python ainsight.py` | 运行完整流程 |
| `python ainsight.py --web` | 仅启动 Web 服务 (http://localhost:8001) |
| `python ainsight.py --all` | 同时运行流程和 Web |
| `python ainsight.py --init` | 初始化数据库并导入 KOL |
| `python ainsight.py --schedule` | 定时任务模式 (08:00/12:00/21:00) |
| `python ainsight.py --limit 20` | 限制抓取 KOL 数量 |
| `python ainsight.py --skip-telegram` | 跳过 Telegram 推送 |

## 环境变量

```env
# 数据库
DATABASE_URL=sqlite+aiosqlite:///./ainsight.db

# 阿里云 DashScope (必填)
DASHSCOPE_API_KEY=sk-xxx
DASHSCOPE_MODEL=qwen-plus

# Telegram 推送 (可选)
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
```

## 数据流程

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   抓取      │ ──▶ │   过滤      │ ──▶ │   聚类      │ ──▶ │   合成      │
│ Twitter/X   │     │ 规则+质量   │     │ FTS+LLM    │     │ 情报包      │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      │                   │                   │                   │
      ▼                   ▼                   ▼                   ▼
  RawContent          过滤垃圾            Topic            IntelligencePackage
  (原始推文)          低质量内容         (主题聚类)          (AI 合成摘要)
```

## 数据库结构

### 核心表

#### KOL (关键意见领袖)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| handle | string | Twitter 用户名 (@xxx) |
| name | string | 显示名称 |
| tier | enum | 等级: god/expert/insider/observer |
| weight | float | 聚类权重 (1.0-3.0) |
| is_active | bool | 是否活跃追踪 |

**KOL 等级说明：**
- `god`: 行业顶级人物 (Karpathy, Yann LeCun)，权重 3.0
- `expert`: 知名从业者 (大厂 AI 负责人)，权重 2.0
- `insider`: 业内人士 (AI 公司员工)，权重 1.5
- `observer`: 关注者 (二手信息传播者)，权重 1.0

#### RawContent (原始内容)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| source_type | enum | 来源类型: x_post/github_repo/blog_post |
| source_url | string | 原始链接 |
| source_url_hash | string | URL 哈希 (去重) |
| kol_id | int | 关联的 KOL |
| text_content | text | 文本内容 |
| likes/retweets/replies | int | 互动数据 |
| topic_id | int | 关联的主题 |
| is_clustered | bool | 是否已聚类 |
| is_synthesized | bool | 是否已合成 |

#### Topic (主题)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| title | string | 主题标题 |
| slug | string | URL 友好标识 |
| keywords | text | 关键词 (FTS 索引) |
| category | enum | 分类: model_release/funding/research/... |
| heat_score | int | 热度评分 (0-100) |
| source_count | int | 关联的原始内容数量 |
| status | enum | 状态: active/merged/archived |

**主题分类：**
- `model_release`: 模型发布
- `funding`: 融资消息
- `product_launch`: 产品发布
- `research`: 研究论文
- `drama`: 行业八卦
- `tutorial`: 教程分享
- `market_signal`: 市场信号

#### IntelligencePackage (情报包)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| intel_id | string | 情报 ID (intel_20240219_xxx) |
| topic_id | int | 关联的主题 |
| tldr | string | 一句话结论 |
| fact_summary | json | 已验证事实列表 |
| action_guide | json | 行动建议 |
| verdict | json | 综合判断 |
| source_count | int | 来源数量 |
| kol_count | int | KOL 数量 |

### 数据处理逻辑

#### 1. 抓取阶段
- 使用 Playwright 抓取 Twitter/X
- 反检测：移除 webdriver 标记
- 去重：URL 哈希检查

#### 2. 过滤阶段
**规则过滤（零成本）：**
- 长度检查：< 30 字符过滤
- 垃圾模式：giveaway/airdrop/抽奖等
- 低价值模式：纯问候/纯表情/纯@
- Hashtag 占比：> 40% 过滤
- 纯转发：RT 开头且无评论

**质量评分（0-10）：**
- 长度分 (0-3)：越长越好
- 互动分 (0-3)：likes/retweets/replies
- KOL 分 (0-2)：根据 tier
- 内容分 (0-2)：是否包含链接/代码/数据

**过滤阈值：**
- 质量分 < 3：跳过聚类
- 质量分 >= 5：可创建新主题
- 质量分 >= 6：高质量内容

#### 3. 聚类阶段
**两阶段聚类：**
1. FTS 快速匹配：SQLite 全文搜索找候选主题
2. LLM 精确判断：决定 merge/create/skip

**聚类决策：**
- `merge`: 合并到已有主题
- `create`: 创建新主题（高质量内容）
- `skip`: 跳过（低价值或重复）

**热度计算：**
```
heat_score = source_count * 5 + likes/100 + retweets/50
```

#### 4. 合成阶段
**触发条件：**
- 来源数 >= 3
- 不同 KOL >= 2
- 有未合成内容
- 不在冷却期（1小时）

**合成输出：**
```json
{
  "tldr": "一句话结论",
  "verified_facts": [
    {"fact": "已验证事实", "sources": [1, 2], "confidence": "high"}
  ],
  "analysis": {
    "implications": ["推断1 [推测]"],
    "uncertainties": ["不确定点"]
  },
  "action_guide": {
    "for_developers": ["行动建议"],
    "watch_list": ["关注点"]
  },
  "verdict": {
    "impact": "significant",
    "urgency": "watch",
    "note": "分析师点评"
  }
}
```

**价值等级：**
- `high`: 独家信息、重大发布
- `medium`: 有用但非独家
- `low`: 重复或营销内容（拒绝合成）
- `reject`: 纯噪音（拒绝合成）

## 项目结构

```
ainsight/
├── ainsight.py              # 主程序入口
├── requirements.txt         # 依赖
├── .env                     # 环境变量
├── config/
│   └── kols.yaml           # KOL 配置
├── src/
│   ├── database/
│   │   ├── models.py       # 数据库模型
│   │   └── service.py      # 数据库服务
│   ├── fetcher/
│   │   ├── playwright_twitter.py  # Twitter 抓取
│   │   └── nitter_gateway.py      # Nitter RSS
│   ├── clustering/
│   │   ├── pipeline.py     # 简化版流水线
│   │   ├── content_filter.py  # 内容过滤器
│   │   ├── topic_cluster.py   # 主题聚类
│   │   └── deduplicator.py    # SimHash 去重
│   ├── processor/
│   │   ├── synthesis.py    # 简化版合成
│   │   └── enhanced_synthesis.py  # 增强版合成
│   ├── notifier/
│   │   └── telegram.py     # Telegram 推送
│   └── web/
│       ├── app.py          # FastAPI 应用
│       ├── templates/      # Jinja2 模板
│       └── static/         # 静态资源
└── logs/
    └── news_funnel.log     # 日志文件
```

## Web API

### 页面路由
| 路径 | 说明 |
|------|------|
| `/` | 首页 - 情报概览 |
| `/topics` | 主题列表 |
| `/topic/{id}` | 主题详情 |
| `/intelligence` | 情报包列表 |
| `/kols` | KOL 管理 |

### API 路由
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stats` | 统计数据 |
| GET | `/api/topics` | 主题列表 |
| GET | `/api/topic/{id}` | 主题详情 |
| GET | `/api/kols` | KOL 列表 |
| POST | `/api/kols` | 创建 KOL |
| PUT | `/api/kols/{id}` | 更新 KOL |
| DELETE | `/api/kols/{id}` | 删除 KOL |
| POST | `/api/translate` | 翻译文本 |

## 技术栈

- **后端**: FastAPI, SQLAlchemy 2.0, asyncio
- **数据库**: SQLite (开发) / PostgreSQL (生产)
- **抓取**: Playwright (反检测)
- **LLM**: 阿里云 DashScope (Qwen-Plus)
- **前端**: Jinja2, i18next (中英文)
- **搜索**: SQLite FTS5 全文搜索

## 配置 KOL

编辑 `config/kols.yaml`:

```yaml
kols:
  - handle: karpathy
    name: Andrej Karpathy
    tier: god
    weight: 3.0

  - handle: sama
    name: Sam Altman
    tier: god
    weight: 3.0

  - handle: ylecun
    name: Yann LeCun
    tier: god
    weight: 3.0
```

## License

MIT
