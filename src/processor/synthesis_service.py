"""
情报合成服务 - 集成数据库操作的完整合成流程

功能：
1. 从数据库获取主题和原始内容
2. 调用合成引擎生成情报
3. 保存情报包到数据库
4. 标记已合成的内容
"""
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Topic, RawContent, KOL, IntelligencePackage, IntelSource,
    TopicStatusEnum
)
from src.logger import get_logger
from .synthesis import SynthesisEngine, SynthesisResult, synthesize_topic

logger = get_logger(__name__)


class SynthesisService:
    """情报合成服务"""

    # 触发合成的最小来源数
    MIN_SOURCES = 3

    def __init__(
        self,
        session: AsyncSession,
        engine: SynthesisEngine
    ):
        """
        初始化合成服务

        Args:
            session: 数据库会话
            engine: 合成引擎
        """
        self.session = session
        self.engine = engine

    async def synthesize_topic(self, topic_id: int) -> Optional[SynthesisResult]:
        """
        合成指定主题的情报包

        Args:
            topic_id: 主题 ID

        Returns:
            SynthesisResult 或 None
        """
        # 1. 获取主题
        topic = await self._get_topic(topic_id)
        if not topic:
            logger.warning(f"主题不存在: {topic_id}")
            return None

        # 2. 获取未合成的原始内容
        contents = await self._get_unsynthesized_contents(topic_id)
        if len(contents) < self.MIN_SOURCES:
            logger.debug(f"主题 {topic_id} 来源不足 ({len(contents)}/{self.MIN_SOURCES})")
            return None

        # 3. 获取 KOL 信息
        kol_map = await self._get_kol_map(contents)

        # 4. 调用合成引擎
        result = await synthesize_topic(
            self.engine,
            topic_id,
            topic.title,
            contents,
            kol_map
        )

        if not result.success:
            logger.error(f"合成失败: {result.error}")
            return result

        # 5. 保存情报包
        intel = await self._save_intelligence_package(topic_id, result)

        # 6. 关联来源
        await self._link_sources(intel.id, contents)

        # 7. 标记内容已合成
        content_ids = [c.id for c in contents]
        await self._mark_synthesized(content_ids)

        await self.session.commit()
        logger.info(f"情报包已保存: {result.intel_id}")

        return result

    async def synthesize_all_pending(self) -> Dict[str, int]:
        """
        合成所有待处理的主题

        Returns:
            统计信息 {"processed": n, "success": n, "failed": n, "skipped": n}
        """
        stats = {"processed": 0, "success": 0, "failed": 0, "skipped": 0}

        # 获取所有活跃主题
        topics = await self._get_active_topics()

        for topic in topics:
            # 检查是否有足够的未合成内容
            contents = await self._get_unsynthesized_contents(topic.id)
            if len(contents) < self.MIN_SOURCES:
                stats["skipped"] += 1
                continue

            stats["processed"] += 1

            result = await self.synthesize_topic(topic.id)
            if result and result.success:
                stats["success"] += 1
            else:
                stats["failed"] += 1

        logger.info(f"批量合成完成: {stats}")
        return stats

    async def update_intelligence(self, topic_id: int) -> Optional[SynthesisResult]:
        """
        更新已有情报包（增量合成）

        Args:
            topic_id: 主题 ID

        Returns:
            SynthesisResult 或 None
        """
        # 获取现有情报包
        existing = await self._get_existing_intel(topic_id)
        if not existing:
            # 没有现有情报包，创建新的
            return await self.synthesize_topic(topic_id)

        # 获取所有内容（包括已合成的）重新合成
        topic = await self._get_topic(topic_id)
        if not topic:
            return None

        contents = await self._get_all_contents(topic_id)
        if not contents:
            return None

        kol_map = await self._get_kol_map(contents)

        # 重新合成
        result = await synthesize_topic(
            self.engine,
            topic_id,
            topic.title,
            contents,
            kol_map
        )

        if not result.success:
            return result

        # 更新情报包
        await self._update_intelligence_package(existing.id, result)

        # 标记所有内容已合成
        content_ids = [c.id for c in contents]
        await self._mark_synthesized(content_ids)

        await self.session.commit()
        logger.info(f"情报包已更新: {result.intel_id}")

        return result

    # ==================== 私有方法 ====================

    async def _get_topic(self, topic_id: int) -> Optional[Topic]:
        """获取主题"""
        result = await self.session.execute(
            select(Topic).where(Topic.id == topic_id)
        )
        return result.scalar_one_or_none()

    async def _get_active_topics(self) -> List[Topic]:
        """获取所有活跃主题"""
        result = await self.session.execute(
            select(Topic)
            .where(Topic.status == TopicStatusEnum.ACTIVE)
            .order_by(Topic.heat_score.desc())
        )
        return list(result.scalars().all())

    async def _get_unsynthesized_contents(self, topic_id: int) -> List[RawContent]:
        """获取未合成的原始内容"""
        result = await self.session.execute(
            select(RawContent)
            .where(
                RawContent.topic_id == topic_id,
                RawContent.is_synthesized == False
            )
            .order_by(RawContent.published_at.desc())
        )
        return list(result.scalars().all())

    async def _get_all_contents(self, topic_id: int) -> List[RawContent]:
        """获取主题下所有原始内容"""
        result = await self.session.execute(
            select(RawContent)
            .where(RawContent.topic_id == topic_id)
            .order_by(RawContent.published_at.desc())
        )
        return list(result.scalars().all())

    async def _get_kol_map(self, contents: List[RawContent]) -> Dict[int, KOL]:
        """获取 KOL 映射"""
        kol_ids = set(c.kol_id for c in contents if c.kol_id)
        if not kol_ids:
            return {}

        result = await self.session.execute(
            select(KOL).where(KOL.id.in_(kol_ids))
        )
        kols = result.scalars().all()
        return {kol.id: kol for kol in kols}

    async def _get_existing_intel(self, topic_id: int) -> Optional[IntelligencePackage]:
        """获取现有情报包"""
        result = await self.session.execute(
            select(IntelligencePackage)
            .where(IntelligencePackage.topic_id == topic_id)
        )
        return result.scalar_one_or_none()

    async def _save_intelligence_package(
        self,
        topic_id: int,
        result: SynthesisResult
    ) -> IntelligencePackage:
        """保存情报包"""
        synthesis = result.synthesis

        intel = IntelligencePackage(
            intel_id=result.intel_id,
            topic_id=topic_id,
            tldr=synthesis.get("tldr"),
            fact_summary=synthesis.get("fact_summary"),
            action_guide=synthesis.get("action_guide"),
            logic_chain=synthesis.get("logic_chain"),
            historical_context=synthesis.get("historical_context"),
            verdict=synthesis.get("verdict"),
            source_count=result.source_count,
            kol_count=result.kol_count,
            synthesis_model=self.engine.model
        )

        self.session.add(intel)
        await self.session.flush()
        return intel

    async def _update_intelligence_package(
        self,
        intel_id: int,
        result: SynthesisResult
    ):
        """更新情报包"""
        synthesis = result.synthesis

        await self.session.execute(
            update(IntelligencePackage)
            .where(IntelligencePackage.id == intel_id)
            .values(
                tldr=synthesis.get("tldr"),
                fact_summary=synthesis.get("fact_summary"),
                action_guide=synthesis.get("action_guide"),
                logic_chain=synthesis.get("logic_chain"),
                historical_context=synthesis.get("historical_context"),
                verdict=synthesis.get("verdict"),
                source_count=result.source_count,
                kol_count=result.kol_count,
                updated_at=datetime.utcnow()
            )
        )

    async def _link_sources(self, intel_id: int, contents: List[RawContent]):
        """关联来源到情报包"""
        for i, content in enumerate(contents):
            source = IntelSource(
                intel_id=intel_id,
                raw_content_id=content.id,
                display_order=i,
                relevance_score=content.relevance_score or 0.0,
                is_primary=(i == 0)  # 第一个为主要来源
            )
            self.session.add(source)

    async def _mark_synthesized(self, content_ids: List[int]):
        """标记内容已合成"""
        await self.session.execute(
            update(RawContent)
            .where(RawContent.id.in_(content_ids))
            .values(is_synthesized=True)
        )
