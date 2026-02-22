"""数据库服务层 - 提供数据库操作接口"""
import hashlib
from datetime import datetime
from typing import Optional, List
from contextlib import asynccontextmanager

from sqlalchemy import select, update, and_, or_, text, func as sql_func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from .models import (
    Base, NewsArticle, NewsSource, FetchLog, User, UserSubscription,
    CategoryEnum, RegionEnum,
    KOL, Topic, RawContent, IntelligencePackage, IntelSource, IntelRelation,
    KOLTierEnum, KOLRoleEnum, SourceTypeEnum, IntelCategoryEnum, TopicStatusEnum,
    create_fts_tables
)
from src.logger import get_database_logger

logger = get_database_logger()


def get_tier_by_followers(followers: int) -> KOLTierEnum:
    """
    根据粉丝数自动判断 KOL 等级

    AI 领域标准：
    - god: >= 50000 粉丝
    - expert: >= 30000 粉丝
    - insider: >= 10000 粉丝
    - observer: < 10000 粉丝
    """
    if followers >= 50000:
        return KOLTierEnum.GOD
    elif followers >= 30000:
        return KOLTierEnum.EXPERT
    elif followers >= 10000:
        return KOLTierEnum.INSIDER
    else:
        return KOLTierEnum.OBSERVER


def get_weight_by_tier(tier: KOLTierEnum) -> float:
    """根据等级获取权重"""
    weights = {
        KOLTierEnum.GOD: 3.0,
        KOLTierEnum.EXPERT: 2.0,
        KOLTierEnum.INSIDER: 1.5,
        KOLTierEnum.OBSERVER: 1.0,
    }
    return weights.get(tier, 1.0)


class DatabaseService:
    """数据库服务类"""

    def __init__(self, database_url: str):
        """
        初始化数据库服务

        Args:
            database_url: 数据库连接URL
                PostgreSQL: postgresql+asyncpg://user:pass@host:port/dbname
                SQLite (开发): sqlite+aiosqlite:///./news_funnel.db
        """
        self.database_url = database_url
        self.engine = create_async_engine(
            database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.debug(f"数据库引擎已创建")

    async def init_db(self):
        """初始化数据库表"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.debug("数据库表已初始化")

    async def close(self):
        """关闭数据库连接"""
        await self.engine.dispose()
        logger.debug("数据库连接已关闭")

    @asynccontextmanager
    async def session(self):
        """获取数据库会话"""
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"数据库事务回滚: {e}")
                raise

    # ==================== 新闻源操作 ====================

    async def get_all_sources(self, enabled_only: bool = True) -> list[NewsSource]:
        """获取所有新闻源"""
        async with self.session() as session:
            query = select(NewsSource)
            if enabled_only:
                query = query.where(NewsSource.enabled == True)
            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_source_by_name(self, name: str) -> Optional[NewsSource]:
        """根据名称获取新闻源"""
        async with self.session() as session:
            result = await session.execute(
                select(NewsSource).where(NewsSource.name == name)
            )
            return result.scalar_one_or_none()

    async def upsert_source(self, source_data: dict) -> NewsSource:
        """插入或更新新闻源"""
        async with self.session() as session:
            # 转换 region 字符串为枚举
            if isinstance(source_data.get("region"), str):
                region_map = {"china": RegionEnum.CHINA, "world": RegionEnum.WORLD}
                source_data["region"] = region_map.get(
                    source_data["region"].lower(), RegionEnum.WORLD
                )

            stmt = pg_insert(NewsSource).values(**source_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["name"],
                set_={
                    "url": stmt.excluded.url,
                    "region": stmt.excluded.region,
                    "source_type": stmt.excluded.source_type,
                    "enabled": stmt.excluded.enabled,
                    "updated_at": datetime.utcnow(),
                }
            )
            await session.execute(stmt)
            await session.commit()

            result = await session.execute(
                select(NewsSource).where(NewsSource.name == source_data["name"])
            )
            return result.scalar_one()

    async def update_source_fetch_time(self, source_id: int):
        """更新新闻源的最后抓取时间"""
        async with self.session() as session:
            await session.execute(
                update(NewsSource)
                .where(NewsSource.id == source_id)
                .values(last_fetch_at=datetime.utcnow())
            )

    # ==================== 新闻文章操作 ====================

    @staticmethod
    def _hash_url(url: str) -> str:
        """生成URL哈希"""
        return hashlib.sha256(url.encode()).hexdigest()

    async def article_exists(self, url: str) -> bool:
        """检查文章是否已存在（去重）"""
        url_hash = self._hash_url(url)
        async with self.session() as session:
            result = await session.execute(
                select(NewsArticle.id).where(NewsArticle.url_hash == url_hash)
            )
            return result.scalar_one_or_none() is not None

    async def save_article(self, article_data: dict) -> Optional[NewsArticle]:
        """
        保存新闻文章（自动去重）

        Returns:
            NewsArticle if saved, None if already exists
        """
        url_hash = self._hash_url(article_data["url"])

        async with self.session() as session:
            # 检查是否已存在
            existing = await session.execute(
                select(NewsArticle.id).where(NewsArticle.url_hash == url_hash)
            )
            if existing.scalar_one_or_none():
                return None

            # 转换枚举
            if isinstance(article_data.get("region"), str):
                region_map = {"china": RegionEnum.CHINA, "world": RegionEnum.WORLD}
                article_data["region"] = region_map.get(
                    article_data["region"].lower(), RegionEnum.WORLD
                )

            if isinstance(article_data.get("category"), str):
                category_map = {
                    "科技": CategoryEnum.TECH,
                    "政治": CategoryEnum.POLITICS,
                    "经济": CategoryEnum.ECONOMY,
                    "社会": CategoryEnum.SOCIETY,
                    "国际": CategoryEnum.INTERNATIONAL,
                    "体育": CategoryEnum.SPORTS,
                    "娱乐": CategoryEnum.ENTERTAINMENT,
                    "其他": CategoryEnum.OTHER,
                }
                article_data["category"] = category_map.get(
                    article_data["category"], CategoryEnum.OTHER
                )

            article = NewsArticle(url_hash=url_hash, **article_data)
            session.add(article)
            await session.commit()
            await session.refresh(article)
            return article

    async def save_articles_batch(self, articles: list[dict]) -> tuple[int, int]:
        """
        批量保存文章

        Returns:
            (total, new_count) - 总数和新增数
        """
        new_count = 0
        for article_data in articles:
            result = await self.save_article(article_data)
            if result:
                new_count += 1
        return len(articles), new_count

    async def get_unprocessed_articles(self, limit: int = 50) -> list[NewsArticle]:
        """获取未处理的文章"""
        async with self.session() as session:
            result = await session.execute(
                select(NewsArticle)
                .where(NewsArticle.is_processed == False)
                .order_by(NewsArticle.fetched_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_unsent_articles(self, limit: int = 20) -> list[NewsArticle]:
        """获取未推送的文章"""
        async with self.session() as session:
            result = await session.execute(
                select(NewsArticle)
                .where(
                    and_(
                        NewsArticle.is_processed == True,
                        NewsArticle.is_sent == False
                    )
                )
                .order_by(NewsArticle.published_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def mark_article_processed(
        self, article_id: int, summary: str, category: CategoryEnum
    ):
        """标记文章已处理"""
        async with self.session() as session:
            await session.execute(
                update(NewsArticle)
                .where(NewsArticle.id == article_id)
                .values(
                    summary=summary,
                    category=category,
                    is_processed=True,
                    processed_at=datetime.utcnow(),
                )
            )

    async def mark_articles_sent(self, article_ids: list[int]):
        """标记文章已推送"""
        async with self.session() as session:
            await session.execute(
                update(NewsArticle)
                .where(NewsArticle.id.in_(article_ids))
                .values(is_sent=True, sent_at=datetime.utcnow())
            )

    async def get_articles_by_filter(
        self,
        category: Optional[CategoryEnum] = None,
        region: Optional[RegionEnum] = None,
        source_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NewsArticle]:
        """按条件查询文章"""
        async with self.session() as session:
            query = select(NewsArticle)

            conditions = []
            if category:
                conditions.append(NewsArticle.category == category)
            if region:
                conditions.append(NewsArticle.region == region)
            if source_id:
                conditions.append(NewsArticle.source_id == source_id)
            if start_date:
                conditions.append(NewsArticle.published_at >= start_date)
            if end_date:
                conditions.append(NewsArticle.published_at <= end_date)

            if conditions:
                query = query.where(and_(*conditions))

            query = query.order_by(NewsArticle.published_at.desc())
            query = query.offset(offset).limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_article_stats(self) -> dict:
        """获取文章统计信息"""
        async with self.session() as session:
            from sqlalchemy import func as sql_func

            # 总数
            total = await session.execute(
                select(sql_func.count(NewsArticle.id))
            )
            total_count = total.scalar()

            # 今日新增
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_result = await session.execute(
                select(sql_func.count(NewsArticle.id))
                .where(NewsArticle.fetched_at >= today)
            )
            today_count = today_result.scalar()

            # 未处理
            unprocessed = await session.execute(
                select(sql_func.count(NewsArticle.id))
                .where(NewsArticle.is_processed == False)
            )
            unprocessed_count = unprocessed.scalar()

            # 未推送
            unsent = await session.execute(
                select(sql_func.count(NewsArticle.id))
                .where(
                    and_(
                        NewsArticle.is_processed == True,
                        NewsArticle.is_sent == False
                    )
                )
            )
            unsent_count = unsent.scalar()

            return {
                "total": total_count,
                "today": today_count,
                "unprocessed": unprocessed_count,
                "unsent": unsent_count,
            }

    # ==================== 抓取日志操作 ====================

    async def create_fetch_log(
        self,
        source_id: int,
        status: str,
        items_fetched: int = 0,
        items_new: int = 0,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> FetchLog:
        """创建抓取日志"""
        async with self.session() as session:
            log = FetchLog(
                source_id=source_id,
                status=status,
                items_fetched=items_fetched,
                items_new=items_new,
                error_message=error_message,
                finished_at=datetime.utcnow(),
                duration_ms=duration_ms,
            )
            session.add(log)
            await session.commit()
            await session.refresh(log)
            return log

    async def get_recent_fetch_logs(
        self, source_id: Optional[int] = None, limit: int = 20
    ) -> list[FetchLog]:
        """获取最近的抓取日志"""
        async with self.session() as session:
            query = select(FetchLog)
            if source_id:
                query = query.where(FetchLog.source_id == source_id)
            query = query.order_by(FetchLog.started_at.desc()).limit(limit)
            result = await session.execute(query)
            return list(result.scalars().all())

    # ==================== 用户操作 (WebUI) ====================

    async def create_user(
        self,
        username: str,
        email: str,
        password_hash: str,
        is_admin: bool = False,
    ) -> User:
        """创建用户"""
        async with self.session() as session:
            user = User(
                username=username,
                email=email,
                password_hash=password_hash,
                is_admin=is_admin,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.username == username)
            )
            return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.email == email)
            )
            return result.scalar_one_or_none()

    async def update_user_telegram(
        self, user_id: int, chat_id: str, username: Optional[str] = None
    ):
        """更新用户的 Telegram 绑定"""
        async with self.session() as session:
            values = {"telegram_chat_id": chat_id}
            if username:
                values["telegram_username"] = username
            await session.execute(
                update(User).where(User.id == user_id).values(**values)
            )

    # ==================== 用户订阅操作 ====================

    async def get_user_subscription(self, user_id: int) -> Optional[UserSubscription]:
        """获取用户订阅配置"""
        async with self.session() as session:
            result = await session.execute(
                select(UserSubscription).where(UserSubscription.user_id == user_id)
            )
            return result.scalar_one_or_none()

    async def update_user_subscription(
        self, user_id: int, subscription_data: dict
    ) -> UserSubscription:
        """更新用户订阅配置"""
        async with self.session() as session:
            existing = await session.execute(
                select(UserSubscription).where(UserSubscription.user_id == user_id)
            )
            subscription = existing.scalar_one_or_none()

            if subscription:
                for key, value in subscription_data.items():
                    setattr(subscription, key, value)
            else:
                subscription = UserSubscription(user_id=user_id, **subscription_data)
                session.add(subscription)

            await session.commit()
            await session.refresh(subscription)
            return subscription

    # ==================== AInsight Pro: KOL 操作 ====================

    async def get_or_create_kol(
        self,
        handle: str,
        platform: str = "x",
        name: Optional[str] = None,
        **kwargs
    ) -> KOL:
        """获取或创建 KOL"""
        async with self.session() as session:
            result = await session.execute(
                select(KOL).where(KOL.handle == handle)
            )
            kol = result.scalar_one_or_none()

            if not kol:
                kol = KOL(
                    handle=handle,
                    platform=platform,
                    name=name or handle,
                    **kwargs
                )
                session.add(kol)
                await session.commit()
                await session.refresh(kol)
                logger.debug(f"创建新 KOL: {handle}")

            return kol

    async def update_kol(self, kol_id: int, **kwargs) -> Optional[KOL]:
        """更新 KOL 信息"""
        async with self.session() as session:
            await session.execute(
                update(KOL).where(KOL.id == kol_id).values(**kwargs)
            )
            result = await session.execute(select(KOL).where(KOL.id == kol_id))
            return result.scalar_one_or_none()

    async def get_active_kols(self, platform: Optional[str] = None) -> list[KOL]:
        """获取活跃的 KOL 列表"""
        async with self.session() as session:
            query = select(KOL).where(KOL.is_active == True)
            if platform:
                query = query.where(KOL.platform == platform)
            query = query.order_by(KOL.tier, KOL.followers.desc())
            result = await session.execute(query)
            return list(result.scalars().all())

    # ==================== AInsight Pro: 主题操作 ====================

    async def get_topic_by_id(self, topic_id: int) -> Optional[Topic]:
        """根据 ID 获取主题"""
        async with self.session() as session:
            result = await session.execute(
                select(Topic).where(Topic.id == topic_id)
            )
            return result.scalar_one_or_none()

    async def get_topic_by_slug(self, slug: str) -> Optional[Topic]:
        """根据 slug 获取主题"""
        async with self.session() as session:
            result = await session.execute(
                select(Topic).where(Topic.slug == slug)
            )
            return result.scalar_one_or_none()

    async def get_active_topics(
        self,
        category: Optional[IntelCategoryEnum] = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "heat"
    ) -> List[Topic]:
        """获取活跃主题列表（预加载关联数据）

        Args:
            category: 分类筛选
            limit: 返回数量
            offset: 偏移量
            sort_by: 排序方式 - heat(热度)/time(时间)/sources(来源数)
        """
        async with self.session() as session:
            query = (
                select(Topic)
                .options(selectinload(Topic.raw_contents))
                .where(Topic.status == TopicStatusEnum.ACTIVE)
            )
            if category:
                query = query.where(Topic.category == category)

            # 根据排序方式排序
            if sort_by == "time":
                query = query.order_by(Topic.last_updated_at.desc(), Topic.heat_score.desc())
            elif sort_by == "sources":
                query = query.order_by(Topic.source_count.desc(), Topic.heat_score.desc())
            else:  # heat (默认)
                query = query.order_by(Topic.heat_score.desc(), Topic.last_updated_at.desc())

            query = query.offset(offset).limit(limit)
            result = await session.execute(query)
            return list(result.scalars().all())

    async def search_topics_fts(self, query_text: str, limit: int = 10) -> list[Topic]:
        """使用 FTS 搜索主题"""
        async with self.session() as session:
            try:
                # SQLite FTS5 查询
                result = await session.execute(
                    text("""
                        SELECT t.* FROM topics t
                        JOIN topics_fts fts ON t.id = fts.rowid
                        WHERE topics_fts MATCH :query
                        AND t.status = :status
                        ORDER BY rank
                        LIMIT :limit
                    """),
                    {
                        "query": query_text,
                        "status": TopicStatusEnum.ACTIVE.value,
                        "limit": limit
                    }
                )
                rows = result.fetchall()
                # 转换为 Topic 对象
                topic_ids = [row.id for row in rows]
                if not topic_ids:
                    return []
                topics_result = await session.execute(
                    select(Topic).where(Topic.id.in_(topic_ids))
                )
                return list(topics_result.scalars().all())
            except Exception as e:
                logger.warning(f"FTS 搜索失败: {e}")
                return []

    async def create_topic(self, topic_data: dict) -> Topic:
        """创建新主题"""
        async with self.session() as session:
            # 处理 category 枚举
            if isinstance(topic_data.get("category"), str):
                try:
                    topic_data["category"] = IntelCategoryEnum(topic_data["category"])
                except ValueError:
                    topic_data["category"] = IntelCategoryEnum.RESEARCH

            topic = Topic(**topic_data)
            session.add(topic)
            await session.commit()
            await session.refresh(topic)
            logger.debug(f"创建主题: {topic.title}")
            return topic

    async def update_topic(self, topic_id: int, **kwargs) -> Optional[Topic]:
        """更新主题"""
        async with self.session() as session:
            kwargs["last_updated_at"] = datetime.utcnow()
            await session.execute(
                update(Topic).where(Topic.id == topic_id).values(**kwargs)
            )
            result = await session.execute(select(Topic).where(Topic.id == topic_id))
            return result.scalar_one_or_none()

    async def merge_topics(self, source_id: int, target_id: int) -> bool:
        """合并主题"""
        async with self.session() as session:
            # 更新源主题状态
            await session.execute(
                update(Topic)
                .where(Topic.id == source_id)
                .values(
                    status=TopicStatusEnum.MERGED,
                    merged_into_id=target_id
                )
            )
            # 迁移原始内容
            await session.execute(
                update(RawContent)
                .where(RawContent.topic_id == source_id)
                .values(topic_id=target_id)
            )
            # 更新目标主题统计
            count_result = await session.execute(
                select(sql_func.count(RawContent.id))
                .where(RawContent.topic_id == target_id)
            )
            new_count = count_result.scalar()
            await session.execute(
                update(Topic)
                .where(Topic.id == target_id)
                .values(
                    source_count=new_count,
                    last_updated_at=datetime.utcnow()
                )
            )
            logger.info(f"合并主题: {source_id} -> {target_id}")
            return True

    # ==================== AInsight Pro: 原始内容操作 ====================

    async def raw_content_exists(self, url_hash: str) -> bool:
        """检查原始内容是否已存在"""
        async with self.session() as session:
            result = await session.execute(
                select(RawContent.id).where(RawContent.source_url_hash == url_hash)
            )
            return result.scalar_one_or_none() is not None

    async def save_raw_content(self, content_data: dict) -> Optional[RawContent]:
        """保存原始内容"""
        url_hash = self._hash_url(content_data.get("source_url", ""))

        async with self.session() as session:
            # 检查是否已存在
            existing = await session.execute(
                select(RawContent.id).where(RawContent.source_url_hash == url_hash)
            )
            if existing.scalar_one_or_none():
                return None

            # 处理 source_type 枚举
            if isinstance(content_data.get("source_type"), str):
                try:
                    content_data["source_type"] = SourceTypeEnum(content_data["source_type"])
                except ValueError:
                    content_data["source_type"] = SourceTypeEnum.NEWS

            content_data["source_url_hash"] = url_hash
            raw_content = RawContent(**content_data)
            session.add(raw_content)
            await session.commit()
            await session.refresh(raw_content)
            return raw_content

    async def get_unclustered_contents(self, limit: int = 50) -> list[RawContent]:
        """获取未聚类的原始内容"""
        async with self.session() as session:
            result = await session.execute(
                select(RawContent)
                .where(RawContent.is_clustered == False)
                .order_by(RawContent.fetched_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_topic_contents(
        self,
        topic_id: int,
        unsynthesized_only: bool = False
    ) -> List[RawContent]:
        """获取主题下的原始内容"""
        async with self.session() as session:
            query = select(RawContent).where(RawContent.topic_id == topic_id)
            if unsynthesized_only:
                query = query.where(RawContent.is_synthesized == False)
            query = query.order_by(RawContent.published_at.desc())
            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_topic_raw_contents(self, topic_id: int) -> List[RawContent]:
        """获取主题下的原始内容（用于合成）"""
        async with self.session() as session:
            result = await session.execute(
                select(RawContent)
                .where(RawContent.topic_id == topic_id)
                .order_by(RawContent.published_at.desc())
            )
            return list(result.scalars().all())

    async def mark_contents_synthesized(self, content_ids: List[int]):
        """标记内容已合成"""
        async with self.session() as session:
            await session.execute(
                update(RawContent)
                .where(RawContent.id.in_(content_ids))
                .values(is_synthesized=True)
            )

    # ==================== AInsight Pro: 情报包操作 ====================

    async def get_intelligence_package(self, intel_id: str) -> Optional[IntelligencePackage]:
        """根据 intel_id 获取情报包"""
        async with self.session() as session:
            result = await session.execute(
                select(IntelligencePackage)
                .where(IntelligencePackage.intel_id == intel_id)
            )
            return result.scalar_one_or_none()

    async def get_topic_intelligence(self, topic_id: int) -> Optional[IntelligencePackage]:
        """获取主题的情报包"""
        async with self.session() as session:
            result = await session.execute(
                select(IntelligencePackage)
                .where(IntelligencePackage.topic_id == topic_id)
            )
            return result.scalar_one_or_none()

    async def create_intelligence_package(
        self,
        topic_id: int,
        intel_id: str,
        synthesis_data: dict
    ) -> IntelligencePackage:
        """创建情报包"""
        async with self.session() as session:
            intel = IntelligencePackage(
                intel_id=intel_id,
                topic_id=topic_id,
                tldr=synthesis_data.get("tldr"),
                fact_summary=synthesis_data.get("fact_summary"),
                action_guide=synthesis_data.get("action_guide"),
                logic_chain=synthesis_data.get("logic_chain"),
                historical_context=synthesis_data.get("historical_context"),
                verdict=synthesis_data.get("verdict"),
                source_count=synthesis_data.get("source_count", 0),
                kol_count=synthesis_data.get("kol_count", 0),
            )
            session.add(intel)
            await session.commit()
            await session.refresh(intel)
            logger.info(f"创建情报包: {intel_id}")
            return intel

    async def update_intelligence_package(
        self,
        intel_id: str,
        synthesis_data: dict
    ) -> Optional[IntelligencePackage]:
        """更新情报包"""
        async with self.session() as session:
            await session.execute(
                update(IntelligencePackage)
                .where(IntelligencePackage.intel_id == intel_id)
                .values(
                    tldr=synthesis_data.get("tldr"),
                    fact_summary=synthesis_data.get("fact_summary"),
                    action_guide=synthesis_data.get("action_guide"),
                    logic_chain=synthesis_data.get("logic_chain"),
                    historical_context=synthesis_data.get("historical_context"),
                    verdict=synthesis_data.get("verdict"),
                    source_count=synthesis_data.get("source_count"),
                    kol_count=synthesis_data.get("kol_count"),
                    updated_at=datetime.utcnow()
                )
            )
            result = await session.execute(
                select(IntelligencePackage)
                .where(IntelligencePackage.intel_id == intel_id)
            )
            return result.scalar_one_or_none()

    async def get_published_intelligence(
        self,
        limit: int = 20,
        offset: int = 0
    ) -> list[IntelligencePackage]:
        """获取已发布的情报包列表"""
        async with self.session() as session:
            result = await session.execute(
                select(IntelligencePackage)
                .where(IntelligencePackage.is_published == True)
                .order_by(IntelligencePackage.published_at.desc())
                .offset(offset)
                .limit(limit)
            )
            return list(result.scalars().all())

    # ==================== AInsight Pro: FTS 初始化 ====================

    async def init_fts_tables(self):
        """初始化 FTS 全文搜索表"""
        # 使用同步方式创建 FTS 表（SQLite 特性）
        from sqlalchemy import create_engine
        sync_url = self.database_url.replace("+aiosqlite", "").replace("+asyncpg", "")
        sync_engine = create_engine(sync_url)
        try:
            create_fts_tables(sync_engine)
            logger.info("FTS 全文搜索表已初始化")
        except Exception as e:
            logger.warning(f"FTS 初始化失败（可能已存在）: {e}")
        finally:
            sync_engine.dispose()

    # ==================== AInsight Pro: 统计信息 ====================

    async def get_clustering_stats(self) -> dict:
        """获取聚类统计信息（优化：单次查询）"""
        async with self.session() as session:
            # 使用单次查询获取所有统计
            result = await session.execute(
                text("""
                    SELECT
                        (SELECT COUNT(*) FROM topics) as topics_total,
                        (SELECT COUNT(*) FROM topics WHERE status = 'active') as topics_active,
                        (SELECT COUNT(*) FROM raw_contents) as contents_total,
                        (SELECT COUNT(*) FROM raw_contents WHERE is_clustered = 1) as contents_clustered,
                        (SELECT COUNT(*) FROM raw_contents WHERE is_synthesized = 1) as contents_synthesized,
                        (SELECT COUNT(*) FROM intelligence_packages) as intel_total,
                        (SELECT COUNT(*) FROM intelligence_packages WHERE is_published = 1) as intel_published,
                        (SELECT COUNT(*) FROM kols) as kols_total
                """)
            )
            row = result.fetchone()

            return {
                "topics": {
                    "total": row[0] or 0,
                    "active": row[1] or 0
                },
                "raw_contents": {
                    "total": row[2] or 0,
                    "clustered": row[3] or 0,
                    "synthesized": row[4] or 0
                },
                "intelligence_packages": {
                    "total": row[5] or 0,
                    "published": row[6] or 0
                },
                "kols": {
                    "total": row[7] or 0
                }
            }
