"""
聚类流水线 - 处理新内容的完整流程

流程：
1. 去重检查
2. FTS 快速匹配候选主题
3. LLM 聚类决策
4. 执行决策（合并/创建/审核）
5. 保存原始内容
6. 检查情报合成触发条件
"""
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy import select, update, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Topic, RawContent, KOL, IntelligencePackage,
    TopicStatusEnum, SourceTypeEnum, IntelCategoryEnum
)
from src.logger import get_logger
from .topic_cluster import TopicClusterer, ClusterResult, ClusterAction

logger = get_logger(__name__)


class ClusteringPipeline:
    """聚类流水线"""

    # 触发情报合成的最小来源数
    MIN_SOURCES_FOR_SYNTHESIS = 3
    # 两次合成的最小间隔（小时）
    SYNTHESIS_COOLDOWN_HOURS = 1

    def __init__(
        self,
        session: AsyncSession,
        clusterer: TopicClusterer,
        synthesis_callback=None
    ):
        """
        初始化流水线

        Args:
            session: 数据库会话
            clusterer: 主题聚类器
            synthesis_callback: 情报合成回调函数（可选）
        """
        self.session = session
        self.clusterer = clusterer
        self.synthesis_callback = synthesis_callback

    async def process_content(self, content: Dict[str, Any]) -> Optional[int]:
        """
        处理新抓取的内容

        Args:
            content: 原始内容字典，包含：
                - text: 文本内容（必填）
                - source_type: 来源类型（必填）
                - source_url: 原始链接（必填）
                - kol_id: KOL ID（可选）
                - kol_name: KOL 名称（可选）
                - title: 标题（可选）
                - published_at: 发布时间（可选）
                - metrics: 互动数据（可选）
                - raw_data: 原始 JSON（可选）

        Returns:
            topic_id 或 None（如果内容已存在）
        """
        text = content.get("text", "")
        source_url = content.get("source_url", "")

        if not text or not source_url:
            logger.warning("内容缺少必填字段: text 或 source_url")
            return None

        # 1. 去重检查
        url_hash = self._hash_url(source_url)
        if await self._content_exists(url_hash):
            logger.debug(f"内容已存在，跳过: {url_hash[:8]}")
            return None

        # 2. FTS 快速匹配候选主题
        candidates = await self._fts_match(text)
        logger.info(f"FTS 匹配到 {len(candidates)} 个候选主题")

        # 3. 聚类决策
        result = await self.clusterer.cluster(content, candidates)
        logger.info(f"聚类决策: {result.action.value}, 相关度: {result.relevance_score:.2f}")

        # 4. 执行决策
        topic_id = await self._execute_decision(result, content)

        # 5. 保存原始内容
        await self._save_raw_content(content, topic_id, url_hash, result.relevance_score)

        # 6. 更新主题统计
        if topic_id:
            await self._update_topic_stats(topic_id)

        # 7. 检查情报合成触发条件
        if topic_id:
            await self._check_synthesis_trigger(topic_id)

        await self.session.commit()
        return topic_id

    async def _content_exists(self, url_hash: str) -> bool:
        """检查内容是否已存在"""
        stmt = select(RawContent.id).where(RawContent.source_url_hash == url_hash)
        result = await self.session.execute(stmt)
        return result.scalar() is not None

    async def _fts_match(self, text: str, limit: int = 5) -> List[Dict[str, Any]]:
        """使用 FTS 快速匹配候选主题"""
        import re
        # 提取关键词：只保留字母、数字、中文
        clean_text = re.sub(r'[^\w\u4e00-\u9fa5\s]', ' ', text[:100])
        # 取前几个词作为搜索关键词
        words = clean_text.split()[:5]
        if not words:
            return await self._fallback_match(text, limit)

        # FTS5 查询格式：用 OR 连接
        keywords = ' OR '.join(f'"{w}"' for w in words if len(w) > 1)

        if not keywords:
            return await self._fallback_match(text, limit)

        try:
            # SQLite FTS5 查询
            query = sql_text("""
                SELECT t.id, t.title, t.category, t.tags, t.heat_score, t.keywords
                FROM topics t
                JOIN topics_fts fts ON t.id = fts.rowid
                WHERE topics_fts MATCH :keywords
                AND t.status = :status
                ORDER BY t.heat_score DESC
                LIMIT :limit
            """)

            result = await self.session.execute(
                query,
                {"keywords": keywords, "status": TopicStatusEnum.ACTIVE.value, "limit": limit}
            )
            rows = result.fetchall()

            return [
                {
                    "id": row.id,
                    "title": row.title,
                    "category": row.category,
                    "tags": row.tags,
                    "heat_score": row.heat_score,
                    "keywords": row.keywords
                }
                for row in rows
            ]
        except Exception as e:
            # FTS 表可能不存在，降级为普通查询
            logger.warning(f"FTS 查询失败，使用降级方案: {e}")
            return await self._fallback_match(text, limit)

    async def _fallback_match(self, text: str, limit: int = 5) -> List[Dict[str, Any]]:
        """降级匹配方案：使用 LIKE 查询"""
        # 提取前几个关键词
        words = text[:50].split()[:3]
        if not words:
            return []

        # 构建 LIKE 条件
        stmt = select(Topic).where(
            Topic.status == TopicStatusEnum.ACTIVE
        ).order_by(Topic.heat_score.desc()).limit(limit)

        result = await self.session.execute(stmt)
        topics = result.scalars().all()

        return [
            {
                "id": t.id,
                "title": t.title,
                "category": t.category.value if t.category else None,
                "tags": t.tags,
                "heat_score": t.heat_score,
                "keywords": t.keywords
            }
            for t in topics
        ]

    async def _execute_decision(
        self,
        result: ClusterResult,
        content: Dict[str, Any]
    ) -> Optional[int]:
        """执行聚类决策"""
        if result.action == ClusterAction.MERGE:
            # 合并到已有主题
            return result.topic_id

        elif result.action == ClusterAction.CREATE:
            # 创建新主题
            if result.new_topic:
                return await self._create_topic(result.new_topic)
            else:
                # LLM 决定创建但没有返回主题信息，需要重新生成
                new_result = await self.clusterer._create_new_topic(content)
                if new_result.new_topic:
                    return await self._create_topic(new_result.new_topic)
                else:
                    # 降级为待审核
                    return await self._create_pending_topic(content, result)

        else:  # REVIEW
            # 创建待审核主题
            return await self._create_pending_topic(content, result)

    async def _create_topic(self, topic_data: Dict[str, Any]) -> int:
        """创建新主题"""
        # 解析 category
        category_str = topic_data.get("category", "research")
        try:
            category = IntelCategoryEnum(category_str)
        except ValueError:
            category = IntelCategoryEnum.RESEARCH

        topic = Topic(
            title=topic_data.get("title", "未命名主题"),
            slug=topic_data.get("slug", f"topic-{datetime.now().timestamp()}"),
            description=topic_data.get("description"),
            keywords=topic_data.get("keywords", ""),
            category=category,
            tags=topic_data.get("tags", []),
            heat_score=1,
            source_count=0,
            status=TopicStatusEnum.ACTIVE,
            first_seen_at=datetime.now(),
            last_updated_at=datetime.now()
        )

        self.session.add(topic)
        await self.session.flush()  # 获取 ID

        logger.info(f"创建新主题: {topic.title} (ID: {topic.id})")
        return topic.id

    async def _create_pending_topic(
        self,
        content: Dict[str, Any],
        result: ClusterResult
    ) -> int:
        """创建待审核主题"""
        # 使用内容的前 30 字符作为临时标题
        title = content.get("title") or content.get("text", "")[:30] + "..."

        topic = Topic(
            title=f"[待审核] {title}",
            slug=f"pending-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            description=f"审核原因: {result.reasoning}",
            keywords=self.clusterer._extract_keywords(content.get("text", "")),
            category=IntelCategoryEnum.RESEARCH,
            tags=["pending_review"],
            heat_score=0,
            source_count=0,
            status=TopicStatusEnum.ACTIVE,  # 暂时设为 active，后续可添加 pending 状态
            first_seen_at=datetime.now(),
            last_updated_at=datetime.now()
        )

        self.session.add(topic)
        await self.session.flush()

        logger.info(f"创建待审核主题: {topic.title} (ID: {topic.id})")
        return topic.id

    async def _save_raw_content(
        self,
        content: Dict[str, Any],
        topic_id: Optional[int],
        url_hash: str,
        relevance_score: float
    ):
        """保存原始内容"""
        # 解析 source_type
        source_type_str = content.get("source_type", "news")
        try:
            source_type = SourceTypeEnum(source_type_str)
        except ValueError:
            source_type = SourceTypeEnum.NEWS

        # 解析 metrics
        metrics = content.get("metrics", {})

        raw_content = RawContent(
            source_type=source_type,
            source_url=content.get("source_url", ""),
            source_url_hash=url_hash,
            kol_id=content.get("kol_id"),
            title=content.get("title"),
            text_content=content.get("text", ""),
            media_urls=content.get("media_urls"),
            code_snippet=content.get("code_snippet"),
            likes=metrics.get("likes", 0),
            retweets=metrics.get("retweets", 0),
            replies=metrics.get("replies", 0),
            stars=metrics.get("stars", 0),
            forks=metrics.get("forks", 0),
            topic_id=topic_id,
            relevance_score=relevance_score,
            is_clustered=topic_id is not None,
            is_synthesized=False,
            published_at=content.get("published_at"),
            clustered_at=datetime.now() if topic_id else None,
            raw_data=content.get("raw_data")
        )

        self.session.add(raw_content)
        logger.debug(f"保存原始内容: {url_hash[:8]}")

    async def _update_topic_stats(self, topic_id: int):
        """更新主题统计信息"""
        # 统计来源数量
        count_stmt = select(RawContent).where(RawContent.topic_id == topic_id)
        result = await self.session.execute(count_stmt)
        source_count = len(result.scalars().all())

        # 计算热度（简单实现：来源数 * 10，上限 100）
        heat_score = min(source_count * 10, 100)

        # 更新主题
        update_stmt = (
            update(Topic)
            .where(Topic.id == topic_id)
            .values(
                source_count=source_count,
                heat_score=heat_score,
                last_updated_at=datetime.now()
            )
        )
        await self.session.execute(update_stmt)

    async def _check_synthesis_trigger(self, topic_id: int):
        """检查是否需要触发情报合成"""
        # 获取主题信息
        stmt = select(Topic).where(Topic.id == topic_id)
        result = await self.session.execute(stmt)
        topic = result.scalar()

        if not topic:
            return

        # 检查来源数量
        if topic.source_count < self.MIN_SOURCES_FOR_SYNTHESIS:
            return

        # 检查是否已有情报包
        intel_stmt = select(IntelligencePackage).where(
            IntelligencePackage.topic_id == topic_id
        )
        intel_result = await self.session.execute(intel_stmt)
        existing_intel = intel_result.scalar()

        if existing_intel:
            # 检查冷却时间
            cooldown = timedelta(hours=self.SYNTHESIS_COOLDOWN_HOURS)
            if existing_intel.updated_at and \
               datetime.now() - existing_intel.updated_at < cooldown:
                logger.debug(f"主题 {topic_id} 在冷却期内，跳过合成")
                return

        # 检查是否有未合成的内容
        unsynthesized_stmt = select(RawContent).where(
            RawContent.topic_id == topic_id,
            RawContent.is_synthesized == False
        )
        unsynthesized_result = await self.session.execute(unsynthesized_stmt)
        unsynthesized = unsynthesized_result.scalars().all()

        if unsynthesized:
            logger.info(f"触发情报合成: 主题 {topic_id}, {len(unsynthesized)} 条未合成内容")
            if self.synthesis_callback:
                await self.synthesis_callback(topic_id)

    def _hash_url(self, url: str) -> str:
        """生成 URL 哈希"""
        return hashlib.sha256(url.encode()).hexdigest()

    def _hash_content(self, text: str) -> str:
        """生成内容哈希"""
        normalized = text.lower().strip()[:500]
        return hashlib.sha256(normalized.encode()).hexdigest()


async def process_batch(
    session: AsyncSession,
    clusterer: TopicClusterer,
    contents: List[Dict[str, Any]],
    synthesis_callback=None
) -> Dict[str, int]:
    """
    批量处理内容

    Args:
        session: 数据库会话
        clusterer: 聚类器
        contents: 内容列表
        synthesis_callback: 合成回调

    Returns:
        统计信息 {"processed": n, "skipped": n, "created": n, "merged": n}
    """
    pipeline = ClusteringPipeline(session, clusterer, synthesis_callback)

    stats = {"processed": 0, "skipped": 0, "created": 0, "merged": 0}

    for content in contents:
        try:
            topic_id = await pipeline.process_content(content)
            if topic_id:
                stats["processed"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            logger.error(f"处理内容失败: {e}")
            stats["skipped"] += 1

    return stats
