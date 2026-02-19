# AInsight Pro - 情报合成数据契约

## 1. 核心 JSON Schema

### 1.1 情报包 (Intelligence Package)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "IntelligencePackage",
  "description": "AI 合成的高密度情报包，支持双栏 UI 展示",
  "type": "object",
  "required": ["id", "topic", "synthesis", "sources", "timeline", "created_at"],
  "properties": {
    "id": {
      "type": "string",
      "description": "情报包唯一标识",
      "example": "intel_20240219_openclaw"
    },
    "topic": {
      "type": "object",
      "description": "主题元信息",
      "properties": {
        "title": { "type": "string", "example": "OpenClaw 发布：开源机器人操控新范式" },
        "slug": { "type": "string", "example": "openclaw-release" },
        "category": {
          "type": "string",
          "enum": ["model_release", "funding", "product_launch", "research", "drama", "tutorial", "market_signal"],
          "description": "情报类型"
        },
        "heat_score": {
          "type": "integer",
          "minimum": 1,
          "maximum": 100,
          "description": "热度评分（基于 KOL 数量、互动量）"
        },
        "tags": {
          "type": "array",
          "items": { "type": "string" },
          "example": ["robotics", "open-source", "embodied-ai"]
        }
      }
    },

    "synthesis": {
      "type": "object",
      "description": "【左栏】AI 合成的洞察层",
      "properties": {
        "tldr": {
          "type": "string",
          "description": "一句话结论（≤50字）",
          "example": "UC Berkeley 开源机器人操控框架，支持 7 种机械臂，可能改变具身智能研发门槛"
        },
        "fact_summary": {
          "type": "object",
          "description": "事实摘要",
          "properties": {
            "what": { "type": "string", "description": "发生了什么" },
            "who": { "type": "string", "description": "关键角色" },
            "when": { "type": "string", "description": "时间节点" },
            "scale": { "type": "string", "description": "规模/数据（如有）" }
          }
        },
        "action_guide": {
          "type": "object",
          "description": "实战行动指南",
          "properties": {
            "for_developers": {
              "type": "array",
              "items": { "type": "string" },
              "description": "开发者应该做什么"
            },
            "for_investors": {
              "type": "array",
              "items": { "type": "string" },
              "description": "投资人应该关注什么"
            },
            "pitfalls": {
              "type": "array",
              "items": { "type": "string" },
              "description": "避坑指南"
            }
          }
        },
        "logic_chain": {
          "type": "array",
          "description": "逻辑推演链",
          "items": {
            "type": "object",
            "properties": {
              "premise": { "type": "string", "description": "前提" },
              "inference": { "type": "string", "description": "推断" },
              "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "置信度"
              }
            }
          },
          "example": [
            {
              "premise": "OpenClaw 支持 7 种主流机械臂",
              "inference": "具身智能研发成本将大幅降低",
              "confidence": "high"
            }
          ]
        },
        "historical_context": {
          "type": "array",
          "description": "历史关联节点",
          "items": {
            "type": "object",
            "properties": {
              "event": { "type": "string" },
              "date": { "type": "string", "format": "date" },
              "relevance": { "type": "string" }
            }
          }
        },
        "verdict": {
          "type": "object",
          "description": "综合判断",
          "properties": {
            "impact_level": {
              "type": "string",
              "enum": ["paradigm_shift", "significant", "incremental", "noise"],
              "description": "影响级别"
            },
            "time_sensitivity": {
              "type": "string",
              "enum": ["act_now", "watch_closely", "background"],
              "description": "时效性"
            },
            "analyst_note": {
              "type": "string",
              "description": "分析师点评（≤100字）"
            }
          }
        }
      }
    },

    "sources": {
      "type": "array",
      "description": "【右栏】原始证据层",
      "items": {
        "type": "object",
        "properties": {
          "id": { "type": "string", "description": "证据 ID" },
          "type": {
            "type": "string",
            "enum": ["x_post", "github_repo", "github_release", "blog_post", "paper", "news"],
            "description": "来源类型"
          },
          "kol": {
            "type": "object",
            "description": "KOL 信息（用于勋章展示）",
            "properties": {
              "name": { "type": "string", "example": "Andrej Karpathy" },
              "handle": { "type": "string", "example": "@karpathy" },
              "avatar_url": { "type": "string" },
              "tier": {
                "type": "string",
                "enum": ["god", "expert", "insider", "observer"],
                "description": "KOL 等级"
              },
              "followers": { "type": "integer" }
            }
          },
          "content": {
            "type": "object",
            "properties": {
              "text": { "type": "string", "description": "原文内容" },
              "media_urls": {
                "type": "array",
                "items": { "type": "string" },
                "description": "图片/视频 URL"
              },
              "code_snippet": { "type": "string", "description": "代码片段（如有）" },
              "url": { "type": "string", "description": "原始链接" }
            }
          },
          "metrics": {
            "type": "object",
            "description": "互动数据",
            "properties": {
              "likes": { "type": "integer" },
              "retweets": { "type": "integer" },
              "replies": { "type": "integer" },
              "stars": { "type": "integer", "description": "GitHub stars" }
            }
          },
          "published_at": { "type": "string", "format": "date-time" },
          "relevance_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "与主题的相关度"
          }
        }
      }
    },

    "timeline": {
      "type": "object",
      "description": "时间轴定位",
      "properties": {
        "event_date": { "type": "string", "format": "date" },
        "era": {
          "type": "string",
          "enum": ["pre_transformer", "gpt_era", "multimodal_era", "agent_era", "embodied_era"],
          "description": "所属时代"
        },
        "milestone_type": {
          "type": "string",
          "enum": ["breakthrough", "iteration", "ecosystem", "controversy"],
          "description": "里程碑类型"
        },
        "related_events": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "intel_id": { "type": "string" },
              "title": { "type": "string" },
              "relation": {
                "type": "string",
                "enum": ["predecessor", "successor", "competitor", "enabler"],
                "description": "关联类型"
              }
            }
          }
        }
      }
    },

    "meta": {
      "type": "object",
      "description": "元数据",
      "properties": {
        "source_count": { "type": "integer", "description": "合成的原始来源数量" },
        "kol_count": { "type": "integer", "description": "涉及的 KOL 数量" },
        "synthesis_model": { "type": "string", "example": "qwen-plus" },
        "created_at": { "type": "string", "format": "date-time" },
        "updated_at": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

---

## 2. 前端双栏交互数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                        AInsight Pro UI                          │
├────────────────────────────┬────────────────────────────────────┤
│      【洞察层 - 左栏】      │       【证言层 - 右栏】            │
│                            │                                    │
│  ┌──────────────────────┐  │  ┌────────────────────────────┐   │
│  │ TLDR: 一句话结论     │  │  │  @karpathy 原帖            │   │
│  └──────────────────────┘  │  │  "OpenClaw is impressive..." │   │
│                            │  │  ❤️ 12.3K  🔄 2.1K          │   │
│  ┌──────────────────────┐  │  └────────────────────────────┘   │
│  │ 📋 事实摘要          │  │                                    │
│  │ What: ...            │  │  ┌────────────────────────────┐   │
│  │ Who: ...             │  │  │  GitHub: openclaw/openclaw  │   │
│  └──────────────────────┘  │  │  ⭐ 2.3K  🍴 156            │   │
│                            │  └────────────────────────────┘   │
│  ┌──────────────────────┐  │                                    │
│  │ 🎯 行动指南          │  │                                    │
│  │ • 开发者: ...        │  │                                    │
│  │ • 避坑: ...          │  │                                    │
│  └──────────────────────┘  │                                    │
│                            │                                    │
│  ┌──────────────────────┐  │                                    │
│  │ KOL 勋章栏           │  │                                    │
│  │ [🥇@karpathy] [🥈@..] │◄─┼──── 点击切换右栏内容              │
│  └──────────────────────┘  │                                    │
└────────────────────────────┴────────────────────────────────────┘
```

---

## 3. API 响应示例

### GET /api/intel/{intel_id}

```json
{
  "id": "intel_20240219_openclaw",
  "topic": {
    "title": "OpenClaw 发布：开源机器人操控新范式",
    "slug": "openclaw-release",
    "category": "model_release",
    "heat_score": 87,
    "tags": ["robotics", "open-source", "embodied-ai", "berkeley"]
  },
  "synthesis": {
    "tldr": "UC Berkeley 开源机器人操控框架 OpenClaw，支持 7 种机械臂，具身智能研发门槛或将大幅降低",
    "fact_summary": {
      "what": "UC Berkeley 发布开源机器人操控框架 OpenClaw",
      "who": "Pieter Abbeel 团队",
      "when": "2024-02-19",
      "scale": "支持 7 种机械臂，含 50+ 预训练策略"
    },
    "action_guide": {
      "for_developers": [
        "立即 clone 仓库，测试与现有硬件的兼容性",
        "关注 issues 区的硬件适配讨论",
        "考虑基于此框架构建垂直应用"
      ],
      "for_investors": [
        "关注具身智能赛道的基础设施层机会",
        "评估对现有机器人公司的冲击"
      ],
      "pitfalls": [
        "目前仅支持仿真环境，真机部署需额外工作",
        "文档尚不完善，社区支持有限"
      ]
    },
    "logic_chain": [
      {
        "premise": "OpenClaw 大幅降低机器人操控的代码门槛",
        "inference": "更多 AI 开发者将进入具身智能领域",
        "confidence": "high"
      },
      {
        "premise": "Pieter Abbeel 团队有持续维护开源项目的历史",
        "inference": "项目大概率会持续迭代",
        "confidence": "medium"
      }
    ],
    "historical_context": [
      {
        "event": "RT-2 发布",
        "date": "2023-07-28",
        "relevance": "同属具身智能基础设施，但 RT-2 未开源"
      }
    ],
    "verdict": {
      "impact_level": "significant",
      "time_sensitivity": "watch_closely",
      "analyst_note": "开源具身智能框架的里程碑，但距离生产可用仍有距离。建议开发者先在仿真环境验证，投资人关注后续生态发展。"
    }
  },
  "sources": [
    {
      "id": "src_001",
      "type": "x_post",
      "kol": {
        "name": "Andrej Karpathy",
        "handle": "@karpathy",
        "avatar_url": "https://...",
        "tier": "god",
        "followers": 892000
      },
      "content": {
        "text": "OpenClaw is impressive. Finally a unified framework for robot manipulation that doesn't require a PhD to set up...",
        "media_urls": [],
        "url": "https://x.com/karpathy/status/..."
      },
      "metrics": {
        "likes": 12300,
        "retweets": 2100,
        "replies": 456
      },
      "published_at": "2024-02-19T10:30:00Z",
      "relevance_score": 0.95
    },
    {
      "id": "src_002",
      "type": "github_repo",
      "kol": {
        "name": "UC Berkeley",
        "handle": "berkeley-rll",
        "tier": "expert"
      },
      "content": {
        "text": "OpenClaw: A Unified Framework for Robot Manipulation",
        "url": "https://github.com/berkeley-rll/openclaw"
      },
      "metrics": {
        "stars": 2300,
        "forks": 156
      },
      "published_at": "2024-02-19T08:00:00Z",
      "relevance_score": 1.0
    }
  ],
  "timeline": {
    "event_date": "2024-02-19",
    "era": "embodied_era",
    "milestone_type": "ecosystem",
    "related_events": [
      {
        "intel_id": "intel_20230728_rt2",
        "title": "Google RT-2: 视觉-语言-动作模型",
        "relation": "predecessor"
      }
    ]
  },
  "meta": {
    "source_count": 8,
    "kol_count": 5,
    "synthesis_model": "qwen-plus",
    "created_at": "2024-02-19T12:00:00Z"
  }
}
```

---

## 4. 数据库表映射

| JSON 字段 | 数据库表 | 说明 |
|-----------|----------|------|
| `id`, `topic`, `synthesis`, `timeline`, `meta` | `intelligence_packages` | 主表 |
| `sources[]` | `intel_sources` | 证据表，外键关联主表 |
| `sources[].kol` | `kols` | KOL 表，独立维护 |
| `timeline.related_events[]` | `intel_relations` | 情报关联表 |

---

## 5. 前端交互协议

### 5.1 勋章点击事件

```typescript
// 用户点击 KOL 勋章时
interface BadgeClickEvent {
  intel_id: string;
  source_id: string;  // 切换右栏到此 source
}

// 前端状态
interface UIState {
  activeIntel: IntelligencePackage;
  activeSourceId: string;  // 当前右栏展示的 source
}
```

### 5.2 右栏切换逻辑

```
用户点击 @karpathy 勋章
    ↓
前端设置 activeSourceId = "src_001"
    ↓
右栏渲染 sources.find(s => s.id === "src_001")
    ↓
展示 Karpathy 的原帖内容
```
