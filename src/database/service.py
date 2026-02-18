"""数据库服务层 - 提供数据库操作接口"""
import hashlib
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from sqlalchemy import select, update, and_, or_
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .models import (
    Base, NewsArticle, NewsSource, FetchLog, User, UserSubscription,
    CategoryEnum, RegionEnum
)
from src.logger import get_database_logger

logger = get_database_logger()


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
