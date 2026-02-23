"""简化版聚类流水线 - 整合过滤、聚类、合成

核心流程：
1. 规则过滤 → 淘汰垃圾内容
2. 质量评分 → 计算内容价值
3. 聚类决策 → 合并/创建/跳过
4. 触发合成 → 满足条件时生成情报包
"""
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select, update, text as sql_text, func as sql_func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Topic, RawContent, KOL, IntelligencePackage,
    TopicStatusEnum, SourceTypeEnum, IntelCategoryEnum
)
from src.logger import get_logger
from .content_filter import ContentFilter

logger = get_logger(__name__)


class ClusterDecision(Enum):
    """聚类决策"""
    MERGE = "merge"    # 合并到已有主题
    CREATE = "create"  # 创建新主题
    SKIP = "skip"      # 跳过（低价值）


@dataclass
class ClusterResult:
    """聚类结果"""
    decision: ClusterDecision
    topic_id: Optional[int] = None
    reason: str = ""
    quality_score: int = 0


class SimplePipeline:
    """简化版聚类流水线"""

    # 配置
    MIN_QUALITY_SCORE = 3          # 最低质量分（0-10）
    MIN_SOURCES_FOR_SYNTHESIS = 3  # 触发合成的最小来源数
    MIN_KOLS_FOR_SYNTHESIS = 2     # 触发合成的最小 KOL 数
    SYNTHESIS_COOLDOWN_HOURS = 1   # 合成冷却时间

    # KOL 权重
    KOL_WEIGHTS = {
        "god": 3.0,
        "expert": 2.0,
        "insider": 1.5,
        "observer": 1.0,
    }

    def __init__(
        self,
        session: AsyncSession,
        llm_client=None,
        model: str = "qwen-plus",
        synthesis_callback=None,
    ):
        self.session = session
        self.llm = llm_client
        self.model = model
        self.synthesis_callback = synthesis_callback
        self.filter = ContentFilter()

    async def process_content(self, content: Dict[str, Any]) -> Optional[int]:
        """
        处理单条内容

        Returns:
            topic_id 或 None
        """
        text = content.get("text", "") or content.get("text_content", "")
        source_url = content.get("source_url", "")

        if not text or not source_url:
            logger.debug("内容缺少必填字段")
            return None

        # 1. 规则过滤
        filter_result = self.filter.filter(content)
        if not filter_result.passed:
            logger.debug(f"内容被过滤: {filter_result.reason}")
            return None

        # 2. 质量评分
        quality_score = self.filter.get_quality_score(content)
        if quality_score < self.MIN_QUALITY_SCORE:
            logger.debug(f"质量分过低: {quality_score}")
            return None

        # 3. URL 去重检查
        url_hash = self._hash_url(source_url)
        if await self._url_exists(url_hash):
            logger.debug("URL 已存在")
            return None

        # 4. 聚类决策
        result = await self._cluster_decision(content, quality_score)

        if result.decision == ClusterDecision.SKIP:
            logger.debug(f"跳过聚类: {result.reason}")
            return None

        # 5. 执行决策
        topic_id = await self._execute_decision(result, content)

        # 6. 保存原始内容
        await self._save_content(content, topic_id, url_hash, quality_score)

        # 7. 更新主题统计
        if topic_id:
            await self._update_topic_stats(topic_id)
            # 8. 检查是否触发合成
            await self._check_synthesis_trigger(topic_id)

        return topic_id

    async def process_batch(self, contents: List[Dict[str, Any]]) -> Dict[str, int]:
        """批量处理"""
        stats = {
            "total": len(contents),
            "filtered": 0,
            "low_quality": 0,
            "duplicate": 0,
            "clustered": 0,
            "skipped": 0,
        }

        # 先批量过滤
        passed, filtered = self.filter.filter_batch(contents)
        stats["filtered"] = len(filtered)

        # 处理通过的内容
        for content in passed:
            try:
                topic_id = await self.process_content(content)
                if topic_id:
                    stats["clustered"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                logger.warning(f"处理失败: {e}")
                stats["skipped"] += 1

        await self.session.commit()
        logger.info(f"批量处理完成: {stats}")
        return stats

    async def _cluster_decision(
        self,
        content: Dict[str, Any],
        quality_score: int
    ) -> ClusterResult:
        """聚类决策"""
        text = content.get("text", "") or content.get("text_content", "")

        # 获取候选主题
        candidates = await self._find_candidates(text)

        if not candidates:
            # 无候选，检查是否值得创建新主题
            if quality_score >= 5:
                return ClusterResult(
                    decision=ClusterDecision.CREATE,
                    reason="高质量内容，创建新主题",
                    quality_score=quality_score
                )
            else:
                return ClusterResult(
                    decision=ClusterDecision.SKIP,
                    reason="质量不足以创建新主题",
                    quality_score=quality_score
                )

        # 有候选，使用 LLM 判断
        if self.llm:
            return await self._llm_cluster(content, candidates, quality_score)
        else:
            # 无 LLM，使用简单规则
            return await self._rule_cluster(content, candidates, quality_score)

    async def _find_candidates(self, text: str, limit: int = 5) -> List[Dict]:
        """查找候选主题"""
        import re

        # 提取关键词
        words = re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fa5]{2,}', text[:200])
        if not words:
            return []

        keywords = ' OR '.join(f'"{w}"' for w in words[:5])

        try:
            # FTS 查询
            query = sql_text("""
                SELECT t.id, t.title, t.category, t.heat_score, t.keywords
                FROM topics t
                JOIN topics_fts fts ON t.id = fts.rowid
                WHERE topics_fts MATCH :keywords
                AND t.status = :status
                ORDER BY t.heat_score DESC
                LIMIT :limit
            """)

            result = await self.session.execute(
                query,
                {"keywords": keywords, "status": "active", "limit": limit}
            )
            rows = result.fetchall()

            return [
                {
                    "id": row.id,
                    "title": row.title,
                    "category": row.category,
                    "heat_score": row.heat_score,
                }
                for row in rows
            ]
        except Exception as e:
            logger.debug(f"FTS 查询失败: {e}")
            # 降级：返回热门主题
            return await self._get_hot_topics(limit)

    async def _get_hot_topics(self, limit: int = 5) -> List[Dict]:
        """获取热门主题（降级方案）"""
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
                "heat_score": t.heat_score,
            }
            for t in topics
        ]

    async def _llm_cluster(
        self,
        content: Dict,
        candidates: List[Dict],
        quality_score: int
    ) -> ClusterResult:
        """使用 LLM 进行聚类决策"""
        text = content.get("text", "")[:500]

        candidates_text = "\n".join([
            f"- ID:{c['id']} 标题:{c['title']} 热度:{c['heat_score']}"
            for c in candidates
        ])

        prompt = f"""判断以下内容应该归属哪个主题。

已有主题：
{candidates_text}

新内容：
{text}

输出 JSON（只输出 JSON）：
{{"action": "merge/create/skip", "topic_id": null, "reason": "一句话理由"}}

规则：
- merge: 内容与某主题高度相关，填写 topic_id
- create: 内容有独立价值，值得创建新主题
- skip: 内容价值不高或与已有主题重复"""

        try:
            response = await self.llm.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200,
                response_format={"type": "json_object"}
            )

            import json
            result = json.loads(response.choices[0].message.content)
            action = result.get("action", "skip")

            if action == "merge" and result.get("topic_id"):
                return ClusterResult(
                    decision=ClusterDecision.MERGE,
                    topic_id=int(result["topic_id"]),
                    reason=result.get("reason", ""),
                    quality_score=quality_score
                )
            elif action == "create":
                return ClusterResult(
                    decision=ClusterDecision.CREATE,
                    reason=result.get("reason", ""),
                    quality_score=quality_score
                )
            else:
                return ClusterResult(
                    decision=ClusterDecision.SKIP,
                    reason=result.get("reason", "LLM 判断跳过"),
                    quality_score=quality_score
                )

        except Exception as e:
            logger.warning(f"LLM 聚类失败: {e}")
            return await self._rule_cluster(content, candidates, quality_score)

    async def _rule_cluster(
        self,
        content: Dict,
        candidates: List[Dict],
        quality_score: int
    ) -> ClusterResult:
        """规则聚类（无 LLM 时的降级方案）"""
        # 简单规则：高质量内容创建新主题，否则合并到最热主题
        if quality_score >= 6:
            return ClusterResult(
                decision=ClusterDecision.CREATE,
                reason="高质量内容",
                quality_score=quality_score
            )
        elif candidates:
            return ClusterResult(
                decision=ClusterDecision.MERGE,
                topic_id=candidates[0]["id"],
                reason="合并到热门主题",
                quality_score=quality_score
            )
        else:
            return ClusterResult(
                decision=ClusterDecision.SKIP,
                reason="无合适主题",
                quality_score=quality_score
            )

    async def _execute_decision(
        self,
        result: ClusterResult,
        content: Dict
    ) -> Optional[int]:
        """执行聚类决策"""
        if result.decision == ClusterDecision.MERGE:
            return result.topic_id

        elif result.decision == ClusterDecision.CREATE:
            return await self._create_topic(content)

        return None

    async def _create_topic(self, content: Dict) -> int:
        """创建新主题"""
        text = content.get("text", "") or content.get("text_content", "")
        title = text[:50].strip()
        if len(text) > 50:
            title += "..."

        # 生成 slug
        import re
        slug_base = re.sub(r'[^a-zA-Z0-9]', '', title.lower())[:20]
        slug = f"{slug_base}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 提取关键词
        keywords = ' '.join(re.findall(r'[A-Za-z]+|[\u4e00-\u9fa5]{2,}', text[:200])[:10])

        topic = Topic(
            title=title,
            slug=slug,
            keywords=keywords,
            category=IntelCategoryEnum.RESEARCH,
            heat_score=1,
            source_count=0,
            status=TopicStatusEnum.ACTIVE,
            first_seen_at=datetime.now(),
            last_updated_at=datetime.now()
        )

        self.session.add(topic)
        await self.session.flush()

        logger.info(f"创建主题: {title[:30]} (ID: {topic.id})")
        return topic.id

    async def _save_content(
        self,
        content: Dict,
        topic_id: Optional[int],
        url_hash: str,
        quality_score: int
    ):
        """保存原始内容"""
        source_type_str = content.get("source_type", "news")
        try:
            source_type = SourceTypeEnum(source_type_str)
        except ValueError:
            source_type = SourceTypeEnum.NEWS

        raw_content = RawContent(
            source_type=source_type,
            source_url=content.get("source_url", ""),
            source_url_hash=url_hash,
            kol_id=content.get("kol_id"),
            author_name=content.get("author_name") or content.get("kol_name"),
            author_handle=content.get("author_handle") or content.get("kol_handle"),
            author_avatar=content.get("author_avatar"),
            is_verified=content.get("is_verified", False),
            title=content.get("title"),
            text_content=content.get("text", "") or content.get("text_content", ""),
            media_urls=content.get("media_urls"),
            likes=content.get("likes", 0),
            retweets=content.get("retweets", 0),
            replies=content.get("replies", 0),
            topic_id=topic_id,
            relevance_score=quality_score / 10.0,
            is_clustered=topic_id is not None,
            is_synthesized=False,
            published_at=content.get("published_at"),
            clustered_at=datetime.now() if topic_id else None,
            raw_data=content.get("raw_data")
        )

        self.session.add(raw_content)

    async def _update_topic_stats(self, topic_id: int):
        """更新主题统计"""
        # 统计来源数
        count_stmt = select(sql_func.count(RawContent.id)).where(
            RawContent.topic_id == topic_id
        )
        count_result = await self.session.execute(count_stmt)
        source_count = count_result.scalar() or 0

        # 统计互动数据
        engagement_stmt = select(
            sql_func.sum(RawContent.likes).label('likes'),
            sql_func.sum(RawContent.retweets).label('retweets'),
        ).where(RawContent.topic_id == topic_id)
        engagement_result = await self.session.execute(engagement_stmt)
        engagement = engagement_result.first()

        # 计算热度
        likes = engagement.likes or 0
        retweets = engagement.retweets or 0
        heat_score = min(
            source_count * 5 + int(likes / 100) + int(retweets / 50),
            100
        )

        # 更新
        await self.session.execute(
            update(Topic)
            .where(Topic.id == topic_id)
            .values(
                source_count=source_count,
                heat_score=heat_score,
                last_updated_at=datetime.now()
            )
        )

    async def _check_synthesis_trigger(self, topic_id: int):
        """检查是否触发情报合成"""
        # 统计来源
        stats_stmt = select(
            sql_func.count(RawContent.id).label('total'),
            sql_func.count(sql_func.distinct(RawContent.kol_id)).label('kols'),
            sql_func.count(RawContent.id).filter(RawContent.is_synthesized == False).label('unsynthesized')
        ).where(RawContent.topic_id == topic_id)

        result = await self.session.execute(stats_stmt)
        stats = result.first()

        if not stats:
            return

        # 检查条件
        if stats.total < self.MIN_SOURCES_FOR_SYNTHESIS:
            return
        if stats.kols < self.MIN_KOLS_FOR_SYNTHESIS:
            return
        if stats.unsynthesized == 0:
            return

        # 检查冷却期
        intel_stmt = select(IntelligencePackage.updated_at).where(
            IntelligencePackage.topic_id == topic_id
        )
        intel_result = await self.session.execute(intel_stmt)
        intel = intel_result.first()

        if intel and intel.updated_at:
            cooldown = timedelta(hours=self.SYNTHESIS_COOLDOWN_HOURS)
            if datetime.now() - intel.updated_at < cooldown:
                return

        # 触发合成
        logger.info(f"触发情报合成: 主题 {topic_id}")
        if self.synthesis_callback:
            await self.synthesis_callback(topic_id)

    async def _url_exists(self, url_hash: str) -> bool:
        """检查 URL 是否已存在"""
        stmt = select(RawContent.id).where(RawContent.source_url_hash == url_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    def _hash_url(self, url: str) -> str:
        """生成 URL 哈希"""
        return hashlib.sha256(url.encode()).hexdigest()
