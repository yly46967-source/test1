"""
运行 Playwright Twitter 抓取并保存到数据库

使用方法：
    python scripts/run_playwright_twitter.py --users karpathy,ylecun --max-tweets 10
    python scripts/run_playwright_twitter.py --from-db --max-tweets 20
    python scripts/run_playwright_twitter.py --from-db --limit 50 --batch-size 5
"""
import asyncio
import argparse
import sys
import os
import hashlib
from datetime import datetime

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.fetcher.playwright_twitter import (
    PlaywrightTwitterFetcher,
    TwitterPost,
    filter_today_tweets,
)
from src.database.service import DatabaseService
from src.database.models import KOL, RawContent, SourceTypeEnum
from src.logger import setup_logging, get_main_logger


class TwitterPipeline:
    """Twitter 抓取并保存流水线"""

    def __init__(self, db: DatabaseService):
        self.db = db
        self.logger = get_main_logger()
        self.stats = {
            "users_processed": 0,
            "users_success": 0,
            "tweets_fetched": 0,
            "tweets_saved": 0,
            "tweets_skipped": 0,
            "errors": 0,
        }

    @staticmethod
    def _hash_url(url: str) -> str:
        """生成 URL 哈希"""
        return hashlib.sha256(url.encode()).hexdigest()

    async def save_tweet(
        self,
        session: AsyncSession,
        tweet: TwitterPost,
        kol: KOL
    ) -> bool:
        """��存单条推文到数据库"""
        if not tweet.post_url:
            return False

        url_hash = self._hash_url(tweet.post_url)

        # 检查是否已存在
        existing = await session.execute(
            select(RawContent.id).where(RawContent.source_url_hash == url_hash)
        )
        if existing.scalar_one_or_none():
            return False

        # 构建内容
        raw_content = RawContent(
            source_type=SourceTypeEnum.X_POST,
            source_url=tweet.post_url,
            source_url_hash=url_hash,
            kol_id=kol.id if kol else None,
            # 作者信息
            author_name=tweet.author_name or kol.name if kol else tweet.author_handle,
            author_handle=tweet.author_handle,
            author_avatar=kol.avatar_url if kol else None,
            # 内容
            title=None,  # 推文没有标题
            text_content=tweet.text or "",
            media_urls=tweet.media_urls or [],
            # 互动数据
            likes=tweet.likes,
            retweets=tweet.retweets,
            replies=tweet.replies,
            # 时间
            published_at=tweet.published_at,
            fetched_at=datetime.now(),
            # 状态
            is_clustered=False,
            is_synthesized=False,
            # 原始数据
            raw_data={
                "is_retweet": tweet.is_retweet,
                "is_reply": tweet.is_reply,
                "views": tweet.views,
                "kol_tier": kol.tier.value if kol and kol.tier else "observer",
            }
        )

        session.add(raw_content)
        return True

    async def fetch_and_save(
        self,
        usernames: list,
        max_tweets: int = 20,
        headless: bool = False,
        batch_size: int = 5,
        kol_map: dict = None,
    ):
        """抓取并保存推文"""
        self.logger.info("=" * 60)
        self.logger.info("Twitter 抓取流水线")
        self.logger.info("=" * 60)
        self.logger.info(f"待抓取用户: {len(usernames)} 个")

        async with PlaywrightTwitterFetcher(
            headless=headless,
            max_tweets=max_tweets
        ) as fetcher:
            results = await fetcher.fetch_multiple_users(
                usernames,
                batch_size=batch_size,
                skip_if_recent=False
            )

        # 保存到数据库
        async with self.db.async_session() as session:
            for username, result in results.items():
                self.stats["users_processed"] += 1

                if not result.success:
                    self.stats["errors"] += 1
                    self.logger.warning(f"@{username}: 抓取失败 - {result.error}")
                    continue

                self.stats["users_success"] += 1
                self.stats["tweets_fetched"] += len(result.tweets)

                # 获取 KOL 信息
                kol = kol_map.get(username) if kol_map else None

                # 保存每条推文
                for tweet in result.tweets:
                    try:
                        saved = await self.save_tweet(session, tweet, kol)
                        if saved:
                            self.stats["tweets_saved"] += 1
                        else:
                            self.stats["tweets_skipped"] += 1
                    except Exception as e:
                        self.logger.warning(f"保存推文失败: {e}")
                        self.stats["errors"] += 1

                self.logger.info(
                    f"@{username}: {len(result.tweets)} 条推文, "
                    f"今日: {len(filter_today_tweets(result.tweets))} 条"
                )

            await session.commit()

        # 更新 KOL 最后抓取时间
        if kol_map:
            async with self.db.async_session() as session:
                for username in results.keys():
                    if results[username].success and username in kol_map:
                        kol = kol_map[username]
                        kol.last_fetched_at = datetime.now()
                        session.add(kol)
                await session.commit()

        # 输出统计
        self.logger.info("-" * 60)
        self.logger.info("抓取统计:")
        self.logger.info(f"  用户处理: {self.stats['users_processed']}")
        self.logger.info(f"  用户成功: {self.stats['users_success']}")
        self.logger.info(f"  推文抓取: {self.stats['tweets_fetched']}")
        self.logger.info(f"  新增保存: {self.stats['tweets_saved']}")
        self.logger.info(f"  跳过重复: {self.stats['tweets_skipped']}")
        self.logger.info(f"  错误: {self.stats['errors']}")
        self.logger.info("=" * 60)

        return self.stats


async def fetch_from_users(usernames: list, max_tweets: int, headless: bool, batch_size: int):
    """从指定用户列表抓取"""
    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ainsight.db")
    db = DatabaseService(database_url)
    await db.init_db()

    try:
        pipeline = TwitterPipeline(db)
        return await pipeline.fetch_and_save(
            usernames=usernames,
            max_tweets=max_tweets,
            headless=headless,
            batch_size=batch_size,
        )
    finally:
        await db.close()


async def fetch_from_db(max_tweets: int, headless: bool, limit: int, batch_size: int):
    """从数据库 KOL 列表抓取"""
    logger = get_main_logger()

    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ainsight.db")
    db = DatabaseService(database_url)
    await db.init_db()

    try:
        # 获取活跃的 X/Twitter KOL
        kols = await db.get_active_kols(platform="x")
        if not kols:
            logger.warning("数据库中没有活跃的 X KOL")
            return {}

        logger.info(f"从数据库加载 {len(kols)} 个 KOL")

        # 限制数量
        kols = kols[:limit]
        usernames = [kol.handle for kol in kols if kol.handle]
        kol_map = {kol.handle: kol for kol in kols}

        logger.info(f"将抓取 {len(usernames)} 个用户")

        # 抓取并保存
        pipeline = TwitterPipeline(db)
        return await pipeline.fetch_and_save(
            usernames=usernames,
            max_tweets=max_tweets,
            headless=headless,
            batch_size=batch_size,
            kol_map=kol_map,
        )

    finally:
        await db.close()


def main():
    parser = argparse.ArgumentParser(description="Playwright Twitter 抓取器")
    parser.add_argument("--users", type=str, help="逗号分隔的用户名列表")
    parser.add_argument("--from-db", action="store_true", help="从数据库 KOL 列表抓取")
    parser.add_argument("--max-tweets", type=int, default=20, help="每个用户最大推文数")
    parser.add_argument("--limit", type=int, default=50, help="最大用户数 (用于 --from-db)")
    parser.add_argument("--batch-size", type=int, default=5, help="批次大小（风控）")
    parser.add_argument("--headless", action="store_true", help="无头模式（可能被检测）")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    setup_logging(level=args.log_level)
    logger = get_main_logger()

    if args.users:
        usernames = [u.strip() for u in args.users.split(",")]
        asyncio.run(fetch_from_users(usernames, args.max_tweets, args.headless, args.batch_size))
    elif args.from_db:
        asyncio.run(fetch_from_db(args.max_tweets, args.headless, args.limit, args.batch_size))
    else:
        # 默认测试
        logger.info("使用默认测试用户: elonmusk, OpenAI")
        asyncio.run(fetch_from_users(["elonmusk", "OpenAI"], args.max_tweets, args.headless, args.batch_size))


if __name__ == "__main__":
    main()
