# AInsight Pro - 主题聚类架构方案

## 1. 技术选型：轻量级方案

在不增加技术复杂度的前提下，使用 **Python + SQLite + Qwen** 实现主题聚类：

```
┌─────────────────────────────────────────────────────────────┐
│                    主题聚类流程                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  新内容 ──► 关键词提取 ──► 相似度匹配 ──► 聚类决策          │
│              (Qwen)        (SQLite FTS)    (Qwen)           │
│                                                             │
│                    ▼                                        │
│              ┌─────────────┐                                │
│              │ 合并到已有  │ ◄── relevance > 0.7            │
│              │ 创建新主题  │ ◄── relevance < 0.3            │
│              │ 人工审核    │ ◄── 0.3 ~ 0.7                  │
│              └─────────────┘                                │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 数据库设计

### 2.1 主题表 (topics)

```sql
CREATE TABLE topics (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,
    tags TEXT,  -- JSON array
    keywords TEXT,  -- 用于 FTS 匹配的关键词
    heat_score INTEGER DEFAULT 0,
    source_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',  -- active/merged/archived
    merged_into TEXT,  -- 如果被合并，指向目标主题
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 全文搜索索引
CREATE VIRTUAL TABLE topics_fts USING fts5(
    title, keywords, tags,
    content='topics',
    content_rowid='rowid'
);
```

### 2.2 原始内容表 (raw_contents)

```sql
CREATE TABLE raw_contents (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,  -- x_post/github/news
    kol_id TEXT,
    content TEXT NOT NULL,
    content_hash TEXT UNIQUE,  -- 用于去重
    url TEXT,
    metrics TEXT,  -- JSON
    published_at TIMESTAMP,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 聚类相关
    topic_id TEXT,  -- 关联的主题
    relevance_score REAL,
    cluster_status TEXT DEFAULT 'pending',  -- pending/clustered/orphan

    FOREIGN KEY (topic_id) REFERENCES topics(id),
    FOREIGN KEY (kol_id) REFERENCES kols(id)
);
```

### 2.3 KOL 表 (kols)

```sql
CREATE TABLE kols (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,  -- x/github/other
    handle TEXT NOT NULL,
    name TEXT,
    avatar_url TEXT,
    bio TEXT,
    followers INTEGER DEFAULT 0,
    tier TEXT DEFAULT 'observer',  -- god/expert/insider/observer
    expertise_areas TEXT,  -- JSON array
    credibility_score REAL DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(platform, handle)
);
```

### 2.4 情报包表 (intelligence_packages)

```sql
CREATE TABLE intelligence_packages (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL,
    synthesis TEXT NOT NULL,  -- JSON: tldr, fact_summary, action_guide, etc.
    timeline TEXT,  -- JSON: event_date, era, milestone_type, related_events
    meta TEXT,  -- JSON: source_count, kol_count, synthesis_model
    status TEXT DEFAULT 'draft',  -- draft/published/archived
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (topic_id) REFERENCES topics(id)
);
```

---

## 3. 聚类算法实现

### 3.1 两阶段聚类

```python
# src/clustering/topic_cluster.py

import hashlib
import json
from typing import Optional, Tuple
from dataclasses import dataclass

@dataclass
class ClusterResult:
    action: str  # merge/create/review
    topic_id: Optional[str]
    new_topic: Optional[dict]
    relevance_score: float
    reasoning: str


class TopicClusterer:
    """主题聚类器"""

    def __init__(self, db_service, llm_client):
        self.db = db_service
        self.llm = llm_client

    async def cluster(self, content: dict) -> ClusterResult:
        """
        对新内容进行聚类

        Args:
            content: 原始内容 dict

        Returns:
            ClusterResult
        """
        # 阶段 1: 快速匹配（SQLite FTS）
        candidates = await self._fast_match(content['text'])

        if not candidates:
            # 没有候选，直接创建新主题
            return await self._create_new_topic(content)

        # 阶段 2: 精确判断（LLM）
        return await self._llm_decide(content, candidates)

    async def _fast_match(self, text: str, limit: int = 5) -> list:
        """
        使用 SQLite FTS 快速匹配候选主题

        Returns:
            候选主题列表，按相关度排序
        """
        # 提取关键词（简单实现：取前 100 字符）
        keywords = text[:100]

        query = """
        SELECT t.*, bm25(topics_fts) as score
        FROM topics_fts
        JOIN topics t ON topics_fts.rowid = t.rowid
        WHERE topics_fts MATCH ?
        AND t.status = 'active'
        ORDER BY score
        LIMIT ?
        """

        async with self.db.session() as session:
            result = await session.execute(query, (keywords, limit))
            return result.fetchall()

    async def _llm_decide(
        self,
        content: dict,
        candidates: list
    ) -> ClusterResult:
        """
        使用 LLM 精确判断聚类决策
        """
        prompt = self._build_cluster_prompt(content, candidates)

        response = await self.llm.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": CLUSTER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)

        return ClusterResult(
            action=result['action'],
            topic_id=result.get('target_topic_id'),
            new_topic=result.get('new_topic'),
            relevance_score=result['relevance_score'],
            reasoning=result['reasoning']
        )

    async def _create_new_topic(self, content: dict) -> ClusterResult:
        """
        使用 LLM 创建新主题
        """
        prompt = f"""
        为以下内容创建一个新主题：

        内容：
        \"\"\"
        {content['text'][:500]}
        \"\"\"

        输出 JSON：
        {{
            "title": "主题标题（≤30字）",
            "category": "model_release/funding/product_launch/research/drama/tutorial/market_signal",
            "tags": ["tag1", "tag2", "tag3"],
            "keywords": "用于搜索匹配的关键词，空格分隔"
        }}
        """

        response = await self.llm.chat.completions.create(
            model="qwen-plus",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )

        new_topic = json.loads(response.choices[0].message.content)

        return ClusterResult(
            action="create",
            topic_id=None,
            new_topic=new_topic,
            relevance_score=0.0,
            reasoning="无匹配候选，创建新主题"
        )

    def _build_cluster_prompt(self, content: dict, candidates: list) -> str:
        """构建聚类判断 prompt"""
        candidates_text = "\n".join([
            f"- ID: {c['id']}, 标题: {c['title']}, 标签: {c['tags']}"
            for c in candidates
        ])

        return f"""
## 任务
判断以下新内容应该合并到哪个已有主题，还是创建新主题。

## 已有主题候选
{candidates_text}

## 新内容
来源: {content.get('source_type', 'unknown')}
作者: {content.get('kol_name', 'unknown')}
内容:
\"\"\"
{content['text'][:500]}
\"\"\"

## 输出 JSON
{{
    "action": "merge/create/review",
    "target_topic_id": "如果 merge，填写目标主题 ID",
    "relevance_score": 0.0-1.0,
    "reasoning": "一句话解释"
}}
"""


CLUSTER_SYSTEM_PROMPT = """
你是一个主题聚类专家。你的任务是判断新内容是否属于已有主题。

判断标准：
- relevance_score > 0.7: 合并到已有主题（action: merge）
- relevance_score < 0.3: 创建新主题（action: create）
- 0.3-0.7: 需要人工审核（action: review）

注意：
1. 同一事件的不同角度报道应该合并
2. 相关但不同的事件应该分开
3. 优先合并到热度更高的主题
"""
```

### 3.2 增量聚类流程

```python
# src/clustering/pipeline.py

class ClusteringPipeline:
    """聚类流水线"""

    def __init__(self, db, llm, clusterer):
        self.db = db
        self.llm = llm
        self.clusterer = clusterer

    async def process_new_content(self, content: dict) -> str:
        """
        处理新抓取的内容

        Returns:
            topic_id
        """
        # 1. 去重检查
        content_hash = self._hash_content(content['text'])
        if await self._exists(content_hash):
            logger.info(f"内容已存在，跳过: {content_hash[:8]}")
            return None

        # 2. 聚类决策
        result = await self.clusterer.cluster(content)

        # 3. 执行决策
        if result.action == "merge":
            topic_id = result.topic_id
            await self._update_topic_stats(topic_id)
        elif result.action == "create":
            topic_id = await self._create_topic(result.new_topic)
        else:  # review
            topic_id = await self._create_pending_topic(content, result)

        # 4. 保存原始内容
        await self._save_content(content, topic_id, result.relevance_score)

        # 5. 检查是否需要触发情报合成
        await self._check_synthesis_trigger(topic_id)

        return topic_id

    async def _check_synthesis_trigger(self, topic_id: str):
        """
        检查是否需要触发情报合成

        触发条件：
        - 主题下有 >= 3 条来源
        - 距离上次合成 >= 1 小时
        - 有新的高权重 KOL 发言
        """
        topic = await self.db.get_topic(topic_id)

        if topic['source_count'] >= 3:
            # 检查是否有未合成的内容
            unsynthesized = await self.db.get_unsynthesized_sources(topic_id)
            if unsynthesized:
                logger.info(f"触发情报合成: {topic_id}")
                await self._trigger_synthesis(topic_id)

    def _hash_content(self, text: str) -> str:
        """生成内容哈希"""
        normalized = text.lower().strip()[:500]
        return hashlib.sha256(normalized.encode()).hexdigest()
```

---

## 4. 性能优化策略

### 4.1 SQLite 优化

```sql
-- 索引优化
CREATE INDEX idx_contents_topic ON raw_contents(topic_id);
CREATE INDEX idx_contents_status ON raw_contents(cluster_status);
CREATE INDEX idx_topics_status ON topics(status);
CREATE INDEX idx_topics_heat ON topics(heat_score DESC);

-- 定期 VACUUM
VACUUM;

-- 分析统计信息
ANALYZE;
```

### 4.2 缓存策略

```python
from functools import lru_cache
import time

class TopicCache:
    """主题缓存"""

    def __init__(self, ttl: int = 300):  # 5 分钟 TTL
        self._cache = {}
        self._ttl = ttl

    def get(self, topic_id: str) -> Optional[dict]:
        if topic_id in self._cache:
            entry = self._cache[topic_id]
            if time.time() - entry['time'] < self._ttl:
                return entry['data']
        return None

    def set(self, topic_id: str, data: dict):
        self._cache[topic_id] = {
            'data': data,
            'time': time.time()
        }

    def invalidate(self, topic_id: str):
        self._cache.pop(topic_id, None)
```

---

## 5. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                      AInsight Pro 架构                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │ X Fetcher   │    │ GitHub      │    │ RSS         │         │
│  │             │    │ Fetcher     │    │ Fetcher     │         │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘         │
│         │                  │                  │                 │
│         └──────────────────┼──────────────────┘                 │
│                            ▼                                    │
│                   ┌─────────────────┐                           │
│                   │ Clustering      │                           │
│                   │ Pipeline        │                           │
│                   └────────┬────────┘                           │
│                            │                                    │
│              ┌─────────────┼─────────────┐                      │
│              ▼             ▼             ▼                      │
│       ┌──────────┐  ┌──────────┐  ┌──────────┐                 │
│       │ topics   │  │ raw_     │  │ kols     │                 │
│       │          │  │ contents │  │          │                 │
│       └────┬─────┘  └──────────┘  └──────────┘                 │
│            │                                                    │
│            ▼                                                    │
│    ┌───────────────┐                                           │
│    │ Synthesis     │ ◄── 触发条件: ≥3 来源                     │
│    │ Engine        │                                           │
│    └───────┬───────┘                                           │
│            │                                                    │
│            ▼                                                    │
│    ┌───────────────┐                                           │
│    │ intelligence_ │                                           │
│    │ packages      │                                           │
│    └───────┬───────┘                                           │
│            │                                                    │
│            ▼                                                    │
│    ┌───────────────┐                                           │
│    │ API / WebUI   │                                           │
│    └───────────────┘                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. 下一步实施计划

| 阶段 | 任务 | 优先级 |
|------|------|--------|
| P0 | 更新数据库模型（topics, raw_contents, kols, intel_packages） | 🔴 |
| P0 | 实现 TopicClusterer 核心逻辑 | 🔴 |
| P1 | 添加 X (Twitter) 数据源抓取 | 🟡 |
| P1 | 实现 SynthesisEngine | 🟡 |
| P2 | 添加 GitHub 数据源 | 🟢 |
| P2 | 实现双栏 WebUI | 🟢 |
