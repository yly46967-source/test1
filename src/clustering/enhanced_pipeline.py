"""
增强版聚类流水线 - 支持多源触发和 KOL 权重

核心改进：
1. N≥3 多源触发机制 - 只有当主题有 3+ 不同来源时才触发合成
2. KOL 权重加权 - 高权重 KOL 的内容优先级更高
3. SimHash 去重 - URL + 内容相似度双重过滤
4. 来源多样性检查 - 确保来源不是单一 KOL
"""
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Set, Tuple
from collections import defaultdict

from sqlalchemy import select, update, text as sql_text, func as sql_func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Topic, RawContent, KOL, IntelligencePackage,
    TopicStatusEnum, SourceTypeEnum, IntelCategoryEnum
)
from src.logger import get_logger
from .topic_cluster import TopicClusterer, ClusterResult, ClusterAction
from .deduplicator import ContentDeduplicator

logger = get_logger(__name__)


class EnhancedClusteringPipeline:
    """增强版聚类流水线"""

    # 触发情报合成的配置
    MIN_SOURCES_FOR_SYNTHESIS = 3      # 最小来源数
    MIN_UNIQUE_KOLS_FOR_SYNTHESIS = 2  # 最小不同 KOL 数
    SYNTHESIS_COOLDOWN_HOURS = 1       # 合成冷却时间

    # KOL 权重配置
    KOL_WEIGHT_MULTIPLIER = {
        "god": 3.0,      # God tier KOL 权重 x3
        "expert": 2.0,   # Expert tier 权重 x2
        "insider": 1.5,  # Insider tier 权重 x1.5
        "observer": 1.0, # Observer tier 权重 x1
    }

    def __init__(
        self,
        session: AsyncSession,
        clusterer: TopicClusterer,
        deduplicator: Optional[ContentDeduplicator] = None,
        synthesis_callback=None,
        min_sources: int = 3,
        min_unique_kols: int = 2,
    ):
        """
        初始化增强版流水线

        Args:
            session: 数据库会话
            clusterer: 主题聚类器
            deduplicator: 去重器（可选，默认创建新实例）
            synthesis_callback: 情报合成回调
            min_sources: 触发合成的最小来源数
            min_unique_kols: 触发合成的最小不同 KOL 数
        """
        self.session = session
        self.clusterer = clusterer
        self.deduplicator = deduplicator or ContentDeduplicator()
        self.synthesis_callback = synthesis_callback
        self.min_sources = min_sources
        self.min_unique_kols = min_unique_kols

    async def process_content(
        self,
        content: Dict[str, Any],
        skip_dedup: bool = False,
    ) -> Optional[int]:
        """
        处理新内容

        Args:
            content: 原始内容字典
            skip_dedup: 是否跳过去重检查

        Returns:
            topic_id 或 None
        """
        text = content.get("text", "")
        source_url = content.get("source_url", "")

        if not text or not source_url:
            logger.warning("内容缺少必填字段")
            return None

        # 1. 去重检查（URL + SimHash）
        if not skip_dedup:
            existing_hashes = await self._get_existing_url_hashes()
            existing_simhashes = await self._get_existing_simhashes()

            is_dup, reason, matched = self.deduplicator.is_duplicate(
                source_url, text, existing_hashes, existing_simhashes
            )

            if is_dup:
                logger.debug(f"内容重复 ({reason}): {source_url[:50]}")
                return None

        # 2. 获取 KOL 信息和权重
        kol_weight = await self._get_kol_weight(content)
        content["_kol_weight"] = kol_weight

        # 3. FTS 快速匹配候选主题
        candidates = await self._fts_match(text)
        logger.info(f"FTS 匹配到 {len(candidates)} 个候选主题")

        # 4. 聚类决策（考虑 KOL 权重）
        result = await self._weighted_cluster(content, candidates)
        logger.info(f"聚类决策: {result.action.value}, 相关度: {result.relevance_score:.2f}")

        # 5. 执行决策
        topic_id = await self._execute_decision(result, content)

        # 6. 保存原始内容
        url_hash = self._hash_url(source_url)
        simhash = self.deduplicator.get_simhash(text)
        await self._save_raw_content(content, topic_id, url_hash, simhash, result.relevance_score)

        # 7. 更新主题统计
        if topic_id:
            await self._update_topic_stats(topic_id)

        # 8. 检查多源触发条件
        if topic_id:
            await self._check_multi_source_trigger(topic_id)

        await self.session.commit()
        return topic_id

    async def process_batch(
        self,
        contents: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        """
        批量处理内容

        Args:
            contents: 内容列表

        Returns:
            统计信息
        """
        # 先进行批量去重
        existing_hashes = await self._get_existing_url_hashes()
        existing_simhashes = await self._get_existing_simhashes()

        unique, duplicates = self.deduplicator.batch_deduplicate(
            contents, existing_hashes, existing_simhashes
        )

        stats = {
            "total": len(contents),
            "unique": len(unique),
            "duplicates": len(duplicates),
            "processed": 0,
            "created": 0,
            "merged": 0,
            "errors": 0,
        }

        # 按 KOL 权重排序（高权重优先处理）
        for content in unique:
            kol_weight = await self._get_kol_weight(content)
            content["_kol_weight"] = kol_weight

        unique.sort(key=lambda x: x.get("_kol_weight", 1.0), reverse=True)

        # 处理唯一内容
        for content in unique:
            try:
                topic_id = await self.process_content(content, skip_dedup=True)
                if topic_id:
                    stats["processed"] += 1
            except Exception as e:
                logger.error(f"处理内容失败: {e}")
                stats["errors"] += 1

        return stats

    async def _get_kol_weight(self, content: Dict[str, Any]) -> float:
        """获取 KOL 权重"""
        kol_id = content.get("kol_id")
        kol_tier = content.get("kol_tier")

        # 如果有 tier 信息，直接使用
        if kol_tier:
            return self.KOL_WEIGHT_MULTIPLIER.get(kol_tier.lower(), 1.0)

        # 从数据库查询
        if kol_id:
            stmt = select(KOL.tier, KOL.weight).where(KOL.id == kol_id)
            result = await self.session.execute(stmt)
            row = result.first()
            if row:
                tier_weight = self.KOL_WEIGHT_MULTIPLIER.get(row.tier.value, 1.0)
                custom_weight = row.weight or 1.0
                return tier_weight * custom_weight

        # 非 KOL 来源
        source_type = content.get("source_type", "")
        if source_type in ("news", "rss"):
            return 0.8  # 新闻源权重稍低
        elif source_type == "github":
            return 1.2  # GitHub 权重稍高

        return 1.0

    async def _weighted_cluster(
        self,
        content: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> ClusterResult:
        """带权重的聚类决策"""
        kol_weight = content.get("_kol_weight", 1.0)

        # 调用基础聚类器
        result = await self.clusterer.cluster(content, candidates)

        # 根据 KOL 权重调整相关度分数
        # 高权重 KOL 的内容更容易创建新主题（避免被合并到低质量主题）
        if kol_weight >= 2.0 and result.action == ClusterAction.MERGE:
            # 高权重 KOL，提高创建新主题的倾向
            adjusted_score = result.relevance_score * 0.9
            if adjusted_score < self.clusterer.merge_threshold:
                logger.info(f"高权重 KOL ({kol_weight})，调整为创建新主题")
                return ClusterResult(
                    action=ClusterAction.CREATE,
                    topic_id=None,
                    new_topic=None,
                    relevance_score=adjusted_score,
                    reasoning=f"高权重 KOL 内容，优先创建新主题"
                )

        return result

    async def _check_multi_source_trigger(self, topic_id: int):
        """
        检查多源触发条件

        触发条件：
        1. 来源数 >= min_sources
        2. 不同 KOL 数 >= min_unique_kols
        3. 有未合成的内容
        4. 不在冷却期内
        """
        # 获取主题的来源统计
        stats = await self._get_topic_source_stats(topic_id)

        source_count = stats["source_count"]
        unique_kols = stats["unique_kols"]
        unsynthesized_count = stats["unsynthesized_count"]

        logger.debug(
            f"主题 {topic_id} 统计: "
            f"来源={source_count}, 不同KOL={unique_kols}, 未合成={unsynthesized_count}"
        )

        # 检查来源数
        if source_count < self.min_sources:
            logger.debug(f"来源数 {source_count} < {self.min_sources}，不触发")
            return

        # 检查 KOL 多样性
        if unique_kols < self.min_unique_kols:
            logger.debug(f"不同 KOL 数 {unique_kols} < {self.min_unique_kols}，不触发")
            return

        # 检查是否有未合成内容
        if unsynthesized_count == 0:
            logger.debug("无未合成内容，不触发")
            return

        # 检查冷却期
        if await self._is_in_cooldown(topic_id):
            logger.debug(f"主题 {topic_id} 在冷却期内")
            return

        # 触发合成
        logger.info(
            f"触发情报合成: 主题 {topic_id}, "
            f"来源={source_count}, KOL={unique_kols}, 未合成={unsynthesized_count}"
        )

        if self.synthesis_callback:
            await self.synthesis_callback(topic_id)

    async def _get_topic_source_stats(self, topic_id: int) -> Dict[str, int]:
        """获取主题的来源统计"""
        # 总来源数
        count_stmt = select(sql_func.count(RawContent.id)).where(
            RawContent.topic_id == topic_id
        )
        count_result = await self.session.execute(count_stmt)
        source_count = count_result.scalar() or 0

        # 不同 KOL 数
        kol_stmt = select(sql_func.count(sql_func.distinct(RawContent.kol_id))).where(
            RawContent.topic_id == topic_id,
            RawContent.kol_id.isnot(None)
        )
        kol_result = await self.session.execute(kol_stmt)
        unique_kols = kol_result.scalar() or 0

        # 未合成内容数
        unsynthesized_stmt = select(sql_func.count(RawContent.id)).where(
            RawContent.topic_id == topic_id,
            RawContent.is_synthesized == False
        )
        unsynthesized_result = await self.session.execute(unsynthesized_stmt)
        unsynthesized_count = unsynthesized_result.scalar() or 0

        return {
            "source_count": source_count,
            "unique_kols": unique_kols,
            "unsynthesized_count": unsynthesized_count,
        }

    async def _is_in_cooldown(self, topic_id: int) -> bool:
        """检查主题是否在合成冷却期内"""
        stmt = select(IntelligencePackage.updated_at).where(
            IntelligencePackage.topic_id == topic_id
        )
        result = await self.session.execute(stmt)
        row = result.first()

        if not row or not row.updated_at:
            return False

        cooldown = timedelta(hours=self.SYNTHESIS_COOLDOWN_HOURS)
        return datetime.now() - row.updated_at < cooldown

    async def _get_existing_url_hashes(self) -> Set[str]:
        """获取已存在的 URL 哈希"""
        stmt = select(RawContent.source_url_hash)
        result = await self.session.execute(stmt)
        return {row.source_url_hash for row in result if row.source_url_hash}

    async def _get_existing_simhashes(self) -> List[Tuple[int, str]]:
        """获取已存在的 SimHash（最近 1000 条）"""
        # 假设 RawContent 有 simhash 字段，如果没有则返回空
        try:
            stmt = select(
                RawContent.source_url_hash
            ).order_by(RawContent.fetched_at.desc()).limit(1000)
            result = await self.session.execute(stmt)
            # 暂时返回空，因为需要添加 simhash 字段
            return []
        except Exception:
            return []

    async def _fts_match(self, text: str, limit: int = 5) -> List[Dict[str, Any]]:
        """FTS 快速匹配候选主题"""
        import re
        clean_text = re.sub(r'[^\w\u4e00-\u9fa5\s]', ' ', text[:100])
        words = clean_text.split()[:5]

        if not words:
            return await self._fallback_match(limit)

        keywords = ' OR '.join(f'"{w}"' for w in words if len(w) > 1)
        if not keywords:
            return await self._fallback_match(limit)

        try:
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
            logger.warning(f"FTS 查询失败: {e}")
            return await self._fallback_match(limit)

    async def _fallback_match(self, limit: int = 5) -> List[Dict[str, Any]]:
        """降级匹配"""
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
            return result.topic_id

        elif result.action == ClusterAction.CREATE:
            if result.new_topic:
                return await self._create_topic(result.new_topic)
            else:
                new_result = await self.clusterer._create_new_topic(content)
                if new_result.new_topic:
                    return await self._create_topic(new_result.new_topic)
                return await self._create_pending_topic(content, result)

        else:  # REVIEW
            return await self._create_pending_topic(content, result)

    async def _create_topic(self, topic_data: Dict[str, Any]) -> int:
        """创建新主题"""
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
        await self.session.flush()

        logger.info(f"创建新主题: {topic.title} (ID: {topic.id})")
        return topic.id

    async def _create_pending_topic(
        self,
        content: Dict[str, Any],
        result: ClusterResult
    ) -> int:
        """创建待审核主题"""
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
            status=TopicStatusEnum.ACTIVE,
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
        simhash: int,
        relevance_score: float
    ):
        """保存原始内容"""
        source_type_str = content.get("source_type", "news")
        try:
            source_type = SourceTypeEnum(source_type_str)
        except ValueError:
            source_type = SourceTypeEnum.NEWS

        metrics = content.get("metrics", {})

        raw_content = RawContent(
            source_type=source_type,
            source_url=content.get("source_url", ""),
            source_url_hash=url_hash,
            kol_id=content.get("kol_id"),
            title=content.get("title"),
            text_content=content.get("text", ""),
            media_urls=content.get("media_urls"),
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

    async def _update_topic_stats(self, topic_id: int):
        """更新主题统计"""
        stats = await self._get_topic_source_stats(topic_id)

        # 计算热度：来源数 * 10 + 不同 KOL 数 * 5
        heat_score = min(
            stats["source_count"] * 10 + stats["unique_kols"] * 5,
            100
        )

        update_stmt = (
            update(Topic)
            .where(Topic.id == topic_id)
            .values(
                source_count=stats["source_count"],
                heat_score=heat_score,
                last_updated_at=datetime.now()
            )
        )
        await self.session.execute(update_stmt)

    def _hash_url(self, url: str) -> str:
        """生成 URL 哈希"""
        return hashlib.sha256(url.encode()).hexdigest()
