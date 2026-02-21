"""三维评分系统 - 基于 ai-daily-digest 的 AI 多维评分

评分维度：
- relevance (1-10): 对 AI/技术从业者的价值
- quality (1-10): 内容深度和原创性
- timeliness (1-10): 时效性

分类标签：
- ai-ml: AI、机器学习、LLM、深度学习
- security: 安全、隐私、漏洞
- engineering: 软件工程、架构、系统设计
- tools: 开发工具、开源项目
- opinion: 行业观点、职业发展
- other: 其他
"""
import json
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Literal

from src.logger import get_logger

logger = get_logger(__name__)


# 分类标签类型
CategoryId = Literal["ai-ml", "security", "engineering", "tools", "opinion", "other"]

VALID_CATEGORIES = {"ai-ml", "security", "engineering", "tools", "opinion", "other"}


@dataclass
class ContentScore:
    """内容评分结果"""
    relevance: int      # 1-10: 对 AI/技术从业者的价值
    quality: int        # 1-10: 内容深度和原创性
    timeliness: int     # 1-10: 时效性
    category: CategoryId
    keywords: List[str] = field(default_factory=list)

    @property
    def total_score(self) -> int:
        """总分 (最高 30)"""
        return self.relevance + self.quality + self.timeliness

    @property
    def weighted_score(self) -> float:
        """加权分数 (relevance 权重更高)"""
        return self.relevance * 1.5 + self.quality * 1.0 + self.timeliness * 0.8

    def is_high_quality(self, threshold: int = 18) -> bool:
        """是否高质量内容"""
        return self.total_score >= threshold

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relevance": self.relevance,
            "quality": self.quality,
            "timeliness": self.timeliness,
            "category": self.category,
            "keywords": self.keywords,
            "total_score": self.total_score,
        }


class ContentScorer:
    """AI 多维评分器

    参考 ai-daily-digest/scripts/digest.ts 的评分逻辑
    """

    # 批处理配置 (参考 ai-daily-digest)
    BATCH_SIZE = 10  # GEMINI_BATCH_SIZE
    MAX_CONCURRENT = 2  # MAX_CONCURRENT_GEMINI

    # 评分 Prompt 模板
    SCORING_PROMPT = """你是一个 AI 技术内容策展人，正在为一份面向技术从业者的情报摘要筛选内容。

请对以下内容进行三个维度的评分（1-10 整数，10 分最高），并为每条内容分配一个分类标签和提取 2-4 个关键词。

## 评分维度

### 1. 相关性 (relevance) - 对 AI/技术从业者的价值
- 10: 所有技术人都应该知道的重大事件/突破（如 GPT-5 发布、重大融资、行业变革）
- 7-9: 对大部分技术从业者有价值
- 4-6: 对特定技术领域有价值
- 1-3: 与技术行业关联不大

### 2. 质量 (quality) - 内容本身的深度
- 10: 深度分析，原创洞见，数据支撑
- 7-9: 有深度，观点独到
- 4-6: 信息准确，表达清晰
- 1-3: 浅尝辄止或纯转述

### 3. 时效性 (timeliness) - 当前是否值得阅读
- 10: 正在发生的重大事件/刚发布的重要工具
- 7-9: 近期热点相关
- 4-6: 常青内容，不过时
- 1-3: 过时或无时效价值

## 分类标签（必须从以下选一个）
- ai-ml: AI、机器学习、LLM、深度学习相关
- security: 安全、隐私、漏洞、加密相关
- engineering: 软件工程、架构、编程语言、系统设计
- tools: 开发工具、开源项目、新发布的库/框架
- opinion: 行业观点、个人思考、职业发展
- other: 以上都不太适合的

## 关键词提取
提取 2-4 个最能代表内容主题的关键词（用英文，简短，如 "Claude", "LLM", "Rust", "performance"）

## 待评分内容

{contents}

请严格按 JSON 格式返回，不要包含 markdown 代码块或其他文字：
{{
  "results": [
    {{
      "index": 0,
      "relevance": 8,
      "quality": 7,
      "timeliness": 9,
      "category": "ai-ml",
      "keywords": ["Claude", "Anthropic", "LLM"]
    }}
  ]
}}"""

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM 客户端，需要有 async generate(prompt) 方法
        """
        self.llm_client = llm_client

    async def score_contents(
        self,
        contents: List[Dict[str, Any]],
    ) -> Dict[int, ContentScore]:
        """
        批量评分内容

        Args:
            contents: 内容列表，每项需要有 text, author 字段

        Returns:
            {index: ContentScore} 字典
        """
        if not self.llm_client:
            logger.warning("[Scorer] 未配置 LLM 客户端，返回默认评分")
            return self._default_scores(len(contents))

        results = {}

        # 分批处理
        for i in range(0, len(contents), self.BATCH_SIZE):
            batch = contents[i:i + self.BATCH_SIZE]
            batch_text = self._format_batch(batch, start_index=i)

            prompt = self.SCORING_PROMPT.format(contents=batch_text)

            try:
                response = await self.llm_client.generate(prompt)
                parsed = self._parse_response(response, start_index=i)
                results.update(parsed)
                logger.debug(f"[Scorer] 批次 {i//self.BATCH_SIZE + 1} 评分完成，{len(parsed)} 条")
            except Exception as e:
                logger.error(f"[Scorer] 批次评分失败: {e}")
                # 失败时使用默认评分
                for j in range(len(batch)):
                    results[i + j] = self._default_score()

        return results

    async def score_single(self, content: Dict[str, Any]) -> ContentScore:
        """评分单条内容"""
        results = await self.score_contents([content])
        return results.get(0, self._default_score())

    def _format_batch(self, contents: List[Dict], start_index: int) -> str:
        """格式化批次内容"""
        lines = []
        for j, content in enumerate(contents):
            idx = start_index + j
            text = content.get("text", "")[:500]  # 截断长文本
            author = content.get("author", "Unknown")
            title = content.get("title", "")

            if title:
                lines.append(f"Index {idx}: [@{author}] {title}\n{text}")
            else:
                lines.append(f"Index {idx}: [@{author}] {text}")

        return "\n\n---\n\n".join(lines)

    def _parse_response(self, response: str, start_index: int = 0) -> Dict[int, ContentScore]:
        """解析 LLM 响应"""
        results = {}

        # 清理 markdown 代码块
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"[Scorer] JSON 解析失败: {e}")
            return results

        for item in data.get("results", []):
            idx = item.get("index", 0)

            # 验证并限制分数范围
            relevance = self._clamp(item.get("relevance", 5))
            quality = self._clamp(item.get("quality", 5))
            timeliness = self._clamp(item.get("timeliness", 5))

            # 验证分类
            category = item.get("category", "other")
            if category not in VALID_CATEGORIES:
                category = "other"

            # 提取关键词
            keywords = item.get("keywords", [])
            if isinstance(keywords, list):
                keywords = [str(k) for k in keywords[:4]]  # 最多 4 个
            else:
                keywords = []

            results[idx] = ContentScore(
                relevance=relevance,
                quality=quality,
                timeliness=timeliness,
                category=category,
                keywords=keywords,
            )

        return results

    def _clamp(self, value: Any, min_val: int = 1, max_val: int = 10) -> int:
        """限制分数范围"""
        try:
            return max(min_val, min(max_val, int(value)))
        except (ValueError, TypeError):
            return 5

    def _default_score(self) -> ContentScore:
        """默认评分"""
        return ContentScore(
            relevance=5,
            quality=5,
            timeliness=5,
            category="other",
            keywords=[],
        )

    def _default_scores(self, count: int) -> Dict[int, ContentScore]:
        """批量默认评分"""
        return {i: self._default_score() for i in range(count)}


# ==================== 过滤器 ====================

class ContentFilter:
    """内容过滤器 - 基于评分筛选高质量内容"""

    def __init__(
        self,
        min_total_score: int = 15,  # 最低总分
        min_relevance: int = 4,     # 最低相关性
        categories: Optional[List[CategoryId]] = None,  # 允许的分类
    ):
        self.min_total_score = min_total_score
        self.min_relevance = min_relevance
        self.categories = set(categories) if categories else None

    def filter(
        self,
        contents: List[Dict[str, Any]],
        scores: Dict[int, ContentScore],
    ) -> List[Dict[str, Any]]:
        """
        过滤内容

        Returns:
            通过筛选的内容列表
        """
        filtered = []

        for i, content in enumerate(contents):
            score = scores.get(i)
            if not score:
                continue

            # 检查总分
            if score.total_score < self.min_total_score:
                continue

            # 检查相关性
            if score.relevance < self.min_relevance:
                continue

            # 检查分类
            if self.categories and score.category not in self.categories:
                continue

            # 附加评分信息
            content["_score"] = score.to_dict()
            filtered.append(content)

        logger.info(f"[Filter] 过滤结果: {len(filtered)}/{len(contents)} 通过")
        return filtered

    def rank(
        self,
        contents: List[Dict[str, Any]],
        scores: Dict[int, ContentScore],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        按评分排序

        Args:
            top_k: 返回前 k 条，None 表示全部

        Returns:
            排序后的内容列表
        """
        scored_contents = []

        for i, content in enumerate(contents):
            score = scores.get(i)
            if score:
                content["_score"] = score.to_dict()
                content["_weighted_score"] = score.weighted_score
                scored_contents.append(content)

        # 按加权分数排序
        scored_contents.sort(key=lambda x: x.get("_weighted_score", 0), reverse=True)

        if top_k:
            scored_contents = scored_contents[:top_k]

        return scored_contents


# ==================== 便捷函数 ====================

async def score_and_filter(
    contents: List[Dict[str, Any]],
    llm_client,
    min_score: int = 15,
) -> List[Dict[str, Any]]:
    """
    便捷函数：评分并过滤内容

    Args:
        contents: 内容列表
        llm_client: LLM 客户端
        min_score: 最低总分阈值

    Returns:
        通过筛选的高质量内容
    """
    scorer = ContentScorer(llm_client)
    scores = await scorer.score_contents(contents)

    filter_ = ContentFilter(min_total_score=min_score)
    return filter_.filter(contents, scores)


async def score_and_rank(
    contents: List[Dict[str, Any]],
    llm_client,
    top_k: int = 20,
) -> List[Dict[str, Any]]:
    """
    便捷函数：评分并排序内容

    Args:
        contents: 内容列表
        llm_client: LLM 客户端
        top_k: 返回前 k 条

    Returns:
        排序后的内容列表
    """
    scorer = ContentScorer(llm_client)
    scores = await scorer.score_contents(contents)

    filter_ = ContentFilter()
    return filter_.rank(contents, scores, top_k=top_k)
