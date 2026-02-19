"""
主题聚类器 - 两阶段聚类实现

阶段 1: SQLite FTS 快速匹配候选主题
阶段 2: LLM 精确判断聚类决策
"""
import json
import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime

from openai import AsyncOpenAI

from src.logger import get_logger

logger = get_logger(__name__)


class ClusterAction(Enum):
    """聚类动作"""
    MERGE = "merge"      # 合并到已有主题
    CREATE = "create"    # 创建新主题
    REVIEW = "review"    # 需要人工审核


@dataclass
class ClusterResult:
    """聚类结果"""
    action: ClusterAction
    topic_id: Optional[int]          # 如果 merge，目标主题 ID
    new_topic: Optional[Dict]        # 如果 create，新主题信息
    relevance_score: float           # 相关度评分 0-1
    reasoning: str                   # 判断理由


# 聚类判断 System Prompt
CLUSTER_SYSTEM_PROMPT = """你是一个主题聚类专家。你的任务是判断新内容是否属于已有主题。

判断标准：
- relevance_score > 0.7: 合并到已有主题（action: merge）
- relevance_score < 0.3: 创建新主题（action: create）
- 0.3-0.7: 需要人工审核（action: review）

注意：
1. 同一事件的不同角度报道应该合并
2. 相关但不同的事件应该分开
3. 优先合并到热度更高的主题
4. 只输出 JSON，不要有其他内容"""


# 新主题创建 System Prompt
CREATE_TOPIC_SYSTEM_PROMPT = """你是一个 AI 领域的主题分析专家。根据内容创建一个新主题。

输出要求：
1. title: 主题标题，≤30字，简洁明了
2. category: 必须是以下之一：model_release/funding/product_launch/research/drama/tutorial/market_signal
3. tags: 3-5 个标签，用于分类和搜索
4. keywords: 用于全文搜索的关键词，空格分隔，包含中英文关键词

只输出 JSON，不要有其他内容"""


class TopicClusterer:
    """主题聚类器 - 两阶段聚类"""

    def __init__(
        self,
        llm_client: AsyncOpenAI,
        model: str = "qwen-plus",
        fts_match_limit: int = 5,
        merge_threshold: float = 0.7,
        create_threshold: float = 0.3
    ):
        """
        初始化聚类器

        Args:
            llm_client: OpenAI 兼容的异步客户端
            model: 使用的模型名称
            fts_match_limit: FTS 匹配返回的最大候选数
            merge_threshold: 合并阈值，>= 此值则合并
            create_threshold: 创建阈值，< 此值则创建新主题
        """
        self.llm = llm_client
        self.model = model
        self.fts_match_limit = fts_match_limit
        self.merge_threshold = merge_threshold
        self.create_threshold = create_threshold

    async def cluster(
        self,
        content: Dict[str, Any],
        candidate_topics: List[Dict[str, Any]]
    ) -> ClusterResult:
        """
        对新内容进行聚类决策

        Args:
            content: 原始内容，包含 text, source_type, kol_name 等
            candidate_topics: FTS 匹配的候选主题列表

        Returns:
            ClusterResult 聚类结果
        """
        text = content.get("text", "")
        if not text:
            raise ValueError("内容文本不能为空")

        # 如果没有候选主题，直接创建新主题
        if not candidate_topics:
            logger.info("无候选主题，创建新主题")
            return await self._create_new_topic(content)

        # 使用 LLM 判断聚类决策
        return await self._llm_decide(content, candidate_topics)

    async def _llm_decide(
        self,
        content: Dict[str, Any],
        candidates: List[Dict[str, Any]]
    ) -> ClusterResult:
        """使用 LLM 精确判断聚类决策"""
        prompt = self._build_cluster_prompt(content, candidates)

        try:
            response = await self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": CLUSTER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            action_str = result.get("action", "review")
            relevance = float(result.get("relevance_score", 0.5))

            # 根据阈值确定最终动作
            if relevance >= self.merge_threshold and action_str == "merge":
                action = ClusterAction.MERGE
            elif relevance < self.create_threshold:
                action = ClusterAction.CREATE
            else:
                action = ClusterAction.REVIEW

            # 如果是 merge 但没有 topic_id，降级为 review
            topic_id = result.get("target_topic_id")
            if action == ClusterAction.MERGE and not topic_id:
                action = ClusterAction.REVIEW
                logger.warning("LLM 返回 merge 但无 topic_id，降级为 review")

            return ClusterResult(
                action=action,
                topic_id=int(topic_id) if topic_id else None,
                new_topic=None,
                relevance_score=relevance,
                reasoning=result.get("reasoning", "")
            )

        except json.JSONDecodeError as e:
            logger.error(f"LLM 返回非 JSON 格式: {e}")
            return ClusterResult(
                action=ClusterAction.REVIEW,
                topic_id=None,
                new_topic=None,
                relevance_score=0.5,
                reasoning="LLM 返回格式错误，需人工审核"
            )
        except Exception as e:
            logger.error(f"聚类决策失败: {e}")
            return ClusterResult(
                action=ClusterAction.REVIEW,
                topic_id=None,
                new_topic=None,
                relevance_score=0.5,
                reasoning=f"聚类决策异常: {str(e)}"
            )

    async def _create_new_topic(self, content: Dict[str, Any]) -> ClusterResult:
        """使用 LLM 创建新主题"""
        text = content.get("text", "")[:500]  # 限制长度

        prompt = f"""为以下内容创建一个新主题：

内容：
\"\"\"
{text}
\"\"\"

输出 JSON：
{{
    "title": "主题标题（≤30字）",
    "category": "model_release/funding/product_launch/research/drama/tutorial/market_signal",
    "tags": ["tag1", "tag2", "tag3"],
    "keywords": "关键词1 关键词2 keyword1 keyword2"
}}"""

        try:
            response = await self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": CREATE_TOPIC_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=300,
                response_format={"type": "json_object"}
            )

            new_topic = json.loads(response.choices[0].message.content)

            # 验证必填字段
            if not new_topic.get("title"):
                new_topic["title"] = self._extract_title(text)
            if not new_topic.get("category"):
                new_topic["category"] = "research"
            if not new_topic.get("tags"):
                new_topic["tags"] = []
            if not new_topic.get("keywords"):
                new_topic["keywords"] = self._extract_keywords(text)

            # 生成 slug
            new_topic["slug"] = self._generate_slug(new_topic["title"])

            return ClusterResult(
                action=ClusterAction.CREATE,
                topic_id=None,
                new_topic=new_topic,
                relevance_score=0.0,
                reasoning="无匹配候选，创建新主题"
            )

        except Exception as e:
            logger.error(f"创建新主题失败: {e}")
            # 降级：使用简单规则创建
            return ClusterResult(
                action=ClusterAction.CREATE,
                topic_id=None,
                new_topic={
                    "title": self._extract_title(text),
                    "slug": self._generate_slug(text[:20]),
                    "category": "research",
                    "tags": [],
                    "keywords": self._extract_keywords(text)
                },
                relevance_score=0.0,
                reasoning=f"LLM 创建失败，使用降级方案: {str(e)}"
            )

    def _build_cluster_prompt(
        self,
        content: Dict[str, Any],
        candidates: List[Dict[str, Any]]
    ) -> str:
        """构建聚类判断 prompt"""
        candidates_text = "\n".join([
            f"- ID: {c.get('id')}, 标题: {c.get('title')}, "
            f"分类: {c.get('category')}, 标签: {c.get('tags')}, "
            f"热度: {c.get('heat_score', 0)}"
            for c in candidates
        ])

        text = content.get("text", "")[:500]
        source_type = content.get("source_type", "unknown")
        kol_name = content.get("kol_name", "unknown")

        return f"""## 任务
判断以下新内容应该合并到哪个已有主题，还是创建新主题。

## 已有主题候选
{candidates_text}

## 新内容
来源类型: {source_type}
作者: {kol_name}
内容:
\"\"\"
{text}
\"\"\"

## 输出 JSON
{{
    "action": "merge/create/review",
    "target_topic_id": "如果 merge，填写目标主题 ID；否则填 null",
    "relevance_score": 0.0-1.0,
    "reasoning": "一句话解释判断理由"
}}"""

    def _extract_title(self, text: str) -> str:
        """从文本提取标题（降级方案）"""
        # 取第一行或前 30 字符
        first_line = text.split("\n")[0].strip()
        if len(first_line) > 30:
            return first_line[:27] + "..."
        return first_line or "未命名主题"

    def _extract_keywords(self, text: str) -> str:
        """从文本提取关键词（降级方案）"""
        # 简单实现：提取英文单词和中文词组
        words = re.findall(r'[A-Za-z]+|[\u4e00-\u9fa5]{2,4}', text[:200])
        # 去重并取前 10 个
        unique_words = list(dict.fromkeys(words))[:10]
        return " ".join(unique_words)

    def _generate_slug(self, title: str) -> str:
        """生成 URL 友好的 slug，确保唯一性"""
        import hashlib

        # 提取英文和数字
        slug = re.sub(r'[^a-zA-Z0-9\s]', '', title.lower())
        slug = re.sub(r'\s+', '-', slug.strip())

        # 如果 slug 为空或太短（<3字符），使用标题哈希
        if not slug or len(slug) < 3:
            title_hash = hashlib.md5(title.encode('utf-8')).hexdigest()[:8]
            slug = f"topic-{title_hash}"
        else:
            # 添加短哈希后缀确保唯一性
            title_hash = hashlib.md5(title.encode('utf-8')).hexdigest()[:6]
            slug = f"{slug[:40]}-{title_hash}"

        return slug[:50]  # 限制长度
