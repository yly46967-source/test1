"""AInsight - AI 情报聚合器主程序"""
import asyncio
import argparse
import sys
import os
import time
import hashlib
from datetime import datetime
from typing import Optional, List

from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.fetcher import (
    load_ainsight_sources,
    fetch_ainsight_sources,
    get_enabled_sources,
    PlaywrightTwitterFetcher,
    TwitterPost,
    filter_today_tweets,
)
from src.clustering import TopicClusterer, EnhancedClusteringPipeline
from src.processor import EnhancedSynthesisEngine
from src.database import DatabaseService
from src.database.models import KOL, RawContent, Topic, TopicStatusEnum, SourceTypeEnum
from src.notifier import TelegramNotifier
from src.logger import setup_logging, get_main_logger

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 全局变量
db: Optional[DatabaseService] = None
logger = None


async def run_ainsight(
    test_mode: bool = False,
    skip_clustering: bool = False,
    skip_synthesis: bool = False,
    skip_telegram: bool = False,
    skip_twitter: bool = False,
    twitter_limit: int = 10,
    concurrency: int = 5,
):
    """AInsight 主运行流程"""
    global db

    logger.info("=" * 50)
    logger.info("AInsight 启动")
    logger.info("=" * 50)

    # 初始化数据库
    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ainsight.db")
    db = DatabaseService(database_url)
    await db.init_db()

    try:
        # FTS 可能导致数据库损坏，暂时跳过
        # await db.init_fts_tables()
        pass
    except Exception as e:
        logger.warning(f"FTS 初始化跳过: {e}")

    logger.info("数据库已连接")

    try:
        items = []

        # 1. Twitter 抓取（新增）
        if not skip_twitter:
            twitter_items = await run_twitter_fetch(limit=twitter_limit, test_mode=test_mode)
            logger.info(f"Twitter 抓取: {len(twitter_items)} 条")
        else:
            logger.info("跳过 Twitter 抓取")

        # 2. RSS 源抓取
        config = load_ainsight_sources()
        sources = get_enabled_sources(config)
        if sources:
            logger.info(f"已加载 {len(sources)} 个 RSS 数据源")
            start_time = time.time()
            rss_items, stats = await fetch_ainsight_sources(sources, config.settings)
            elapsed = time.time() - start_time
            logger.info(
                f"RSS 抓取完成: {stats['success']} 成功, {stats['failed']} 失败, "
                f"{stats['total_items']} 条内容, 耗时 {elapsed:.1f}s"
            )

            # 保存 RSS 内容到数据库
            if rss_items:
                saved_count = await save_rss_items_to_db(rss_items)
                logger.info(f"RSS 内容保存: {saved_count} 条新增")

        if test_mode:
            logger.info("测试模式: 限制处理数量")

        # 3. 聚类处理
        if not skip_clustering:
            await run_clustering_from_db()
        else:
            logger.info("跳过聚类处理")

        # 4. 情报合成
        if not skip_synthesis:
            await run_synthesis()
        else:
            logger.info("跳过情报合成")

        # 5. Telegram 推送
        if not skip_telegram:
            await send_intelligence_digest()
        else:
            logger.info("跳过 Telegram 推送")

        # 显示统计
        clustering_stats = await db.get_clustering_stats()
        logger.info(
            f"统计: 主题 {clustering_stats['topics']['active']} 个, "
            f"内容 {clustering_stats['raw_contents']['total']} 条, "
            f"情报包 {clustering_stats['intelligence_packages']['total']} 个"
        )

        logger.info("运行完成")

    except Exception as e:
        logger.error(f"运行出错: {e}", exc_info=True)
        raise
    finally:
        if db:
            await db.close()


async def run_twitter_fetch(limit: int = 10, test_mode: bool = False) -> List[dict]:
    """运行 Twitter 抓取并保存到数据库"""
    logger.info("=" * 50)
    logger.info("Twitter 抓取")
    logger.info("=" * 50)

    # 获取活跃的 X KOL
    kols = await db.get_active_kols(platform="x")
    if not kols:
        logger.warning("数据库中没有活跃的 X KOL")
        return []

    # 限制数量
    kols = kols[:limit]
    usernames = [kol.handle for kol in kols if kol.handle]
    kol_map = {kol.handle: kol for kol in kols}

    logger.info(f"将抓取 {len(usernames)} 个 Twitter 用户")

    if test_mode:
        usernames = usernames[:3]
        logger.info(f"测试模式: 只抓取 {len(usernames)} 个用户")

    saved_items = []

    try:
        async with PlaywrightTwitterFetcher(
            headless=False,
            max_tweets=20
        ) as fetcher:
            results = await fetcher.fetch_multiple_users(
                usernames,
                batch_size=5,
                skip_if_recent=False
            )

        # 保存到数据库
        async with db.async_session() as session:
            for username, result in results.items():
                if not result.success:
                    logger.warning(f"@{username}: 抓取失败 - {result.error}")
                    continue

                kol = kol_map.get(username)

                for tweet in result.tweets:
                    if not tweet.post_url:
                        continue

                    url_hash = hashlib.sha256(tweet.post_url.encode()).hexdigest()

                    # 检查是否已存在
                    existing = await session.execute(
                        select(RawContent.id).where(RawContent.source_url_hash == url_hash)
                    )
                    if existing.scalar_one_or_none():
                        continue

                    # 保存
                    raw_content = RawContent(
                        source_type=SourceTypeEnum.X_POST,
                        source_url=tweet.post_url,
                        source_url_hash=url_hash,
                        kol_id=kol.id if kol else None,
                        author_name=tweet.author_name or (kol.name if kol else tweet.author_handle),
                        author_handle=tweet.author_handle,
                        author_avatar=tweet.author_avatar or (kol.avatar_url if kol else None),
                        is_verified=tweet.is_verified,
                        title=None,
                        text_content=tweet.text or "",
                        media_urls=tweet.media_urls or [],
                        likes=tweet.likes,
                        retweets=tweet.retweets,
                        replies=tweet.replies,
                        published_at=tweet.published_at,
                        fetched_at=datetime.now(),
                        is_clustered=False,
                        is_synthesized=False,
                        raw_data={
                            # 原文格式化数据（保留段落）
                            "formatted_text": tweet.text or "",
                            "paragraphs": (tweet.text or "").split("\n\n") if tweet.text else [],
                            # 元数据
                            "is_retweet": tweet.is_retweet,
                            "is_reply": tweet.is_reply,
                            "views": tweet.views,
                            "kol_tier": kol.tier.value if kol and kol.tier else "observer",
                        }
                    )
                    session.add(raw_content)
                    saved_items.append({"url": tweet.post_url, "text": tweet.text[:50]})

                logger.info(f"@{username}: {len(result.tweets)} 条推文")

            await session.commit()

        # 更新 KOL 最后抓取时间
        async with db.async_session() as session:
            for username in results.keys():
                if results[username].success and username in kol_map:
                    kol = kol_map[username]
                    kol.last_fetched_at = datetime.now()
                    session.add(kol)
            await session.commit()

        logger.info(f"Twitter 抓取完成: 保存 {len(saved_items)} 条新推文")

    except Exception as e:
        logger.error(f"Twitter 抓取失败: {e}")

    return saved_items


async def save_rss_items_to_db(items) -> int:
    """保存 RSS 抓取的内容到数据库"""
    saved_count = 0

    async with db.async_session() as session:
        for item in items:
            if not item.source_url:
                continue

            url_hash = hashlib.sha256(item.source_url.encode()).hexdigest()

            # 检查是否已存在
            existing = await session.execute(
                select(RawContent.id).where(RawContent.source_url_hash == url_hash)
            )
            if existing.scalar_one_or_none():
                continue

            # 确定 source_type
            source_type = SourceTypeEnum.NEWS
            if item.source_type:
                try:
                    source_type = SourceTypeEnum(item.source_type)
                except ValueError:
                    if "blog" in item.source_type.lower():
                        source_type = SourceTypeEnum.BLOG_POST

            raw_content = RawContent(
                source_type=source_type,
                source_url=item.source_url,
                source_url_hash=url_hash,
                title=item.title,
                text_content=item.text or "",
                author_name=item.kol_name,
                author_handle=item.kol_handle,
                media_urls=item.media_urls or [],
                published_at=item.published_at,
                fetched_at=datetime.now(),
                is_clustered=False,
                is_synthesized=False,
                raw_data=item.raw_data,
            )
            session.add(raw_content)
            saved_count += 1

        await session.commit()

    return saved_count


async def run_clustering_from_db():
    """从数据库读取未聚类内容并处理"""
    logger.info("=" * 50)
    logger.info("聚类处理")
    logger.info("=" * 50)

    llm_client = AsyncOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    clusterer = TopicClusterer(
        llm_client=llm_client,
        model=os.getenv("LLM_MODEL", "qwen-plus"),
    )

    async with db.session() as session:
        # 在同一个 session 中获取未聚类内容
        from sqlalchemy import select
        query = select(RawContent).where(RawContent.is_clustered == False).limit(50)
        result = await session.execute(query)
        unclustered = result.scalars().all()

        if not unclustered:
            logger.info("没有待聚类的内容")
            return

        logger.info(f"待聚类内容: {len(unclustered)} 条")

        pipeline = EnhancedClusteringPipeline(session, clusterer)

        processed = 0
        skipped = 0

        for content in unclustered:
            try:
                content_dict = {
                    "text": content.text_content,
                    "source_type": content.source_type.value if content.source_type else "news",
                    "source_url": content.source_url,
                    "title": content.title,
                    "published_at": content.published_at,
                    "kol_name": content.author_name,
                    "kol_handle": content.author_handle,
                }

                # 使用 cluster_existing_content 而不是 process_content
                # 这样不会创建新的 RawContent，只做聚类决策
                topic_id = await pipeline.cluster_existing_content(content_dict)
                if topic_id:
                    # 更新内容的 topic_id 和聚类状态
                    content.topic_id = topic_id
                    content.is_clustered = True
                    content.clustered_at = datetime.now()
                    processed += 1
                    logger.debug(f"内容 {content.id} 聚类到主题 {topic_id}")
                else:
                    skipped += 1

            except Exception as e:
                logger.warning(f"处理内容失败: {e}")
                await session.rollback()
                skipped += 1

        await session.commit()

    logger.info(f"聚类完成: {processed} 处理, {skipped} 跳过")


async def run_synthesis():
    """运行情报合成"""
    logger.info("检查情报合成触发条件...")

    llm_client = AsyncOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    engine = EnhancedSynthesisEngine(
        llm_client=llm_client,
        model=os.getenv("LLM_MODEL", "qwen-plus"),
    )

    # 获取待合成的主题
    async with db.session() as session:
        from sqlalchemy import select
        from src.database.models import Topic, TopicStatusEnum

        result = await session.execute(
            select(Topic).where(Topic.status == TopicStatusEnum.ACTIVE)
        )
        topics = result.scalars().all()

        success_count = 0
        for topic in topics:
            if topic.source_count >= 3:  # 至少 3 个来源才合成
                # 获取主题下的原始内容
                raw_contents = await db.get_topic_raw_contents(topic.id)
                if raw_contents:
                    sources = [
                        {
                            "source_id": c.id,
                            "text": c.text_content,
                            "kol_handle": c.kol_handle or "",
                            "kol_tier": "observer",
                            "published_at": c.published_at.isoformat() if c.published_at else "",
                        }
                        for c in raw_contents
                    ]
                    result = await engine.synthesize(topic.title, sources, topic.id)
                    if result.success:
                        success_count += 1

        logger.info(f"情报合成: {success_count} 个主题")


async def send_intelligence_digest():
    """发送情报摘要到 Telegram"""
    logger.info("准备发送情报摘要...")

    notifier = TelegramNotifier()
    stats = await db.get_clustering_stats()
    top_topics = await db.get_active_topics(limit=10)

    topics_data = [
        {
            "title": t.title,
            "category": t.category.value if t.category else "news",
            "source_count": t.source_count,
            "heat_score": t.heat_score,
        }
        for t in top_topics
    ]

    daily_stats = {
        "new_contents": stats["raw_contents"]["total"],
        "active_topics": stats["topics"]["active"],
        "intel_packages": stats["intelligence_packages"]["total"],
    }

    await notifier.send_daily_digest(daily_stats, topics_data)
    logger.info("情报推送完成")


async def run_scheduler():
    """定时任务调度器"""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    import pytz

    beijing_tz = pytz.timezone('Asia/Shanghai')
    scheduler = AsyncIOScheduler(timezone=beijing_tz)

    async def scheduled_run():
        logger.info("=" * 50)
        logger.info(f"定时任务: {datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 50)
        await run_ainsight()

    scheduler.add_job(scheduled_run, CronTrigger(hour=8, minute=0, timezone=beijing_tz))
    scheduler.add_job(scheduled_run, CronTrigger(hour=12, minute=0, timezone=beijing_tz))
    scheduler.add_job(scheduled_run, CronTrigger(hour=21, minute=0, timezone=beijing_tz))

    scheduler.start()
    logger.info("定时任务已启动（北京时间 08:00, 12:00, 21:00）")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        scheduler.shutdown()


def main():
    global logger

    parser = argparse.ArgumentParser(description="AInsight - AI 情报聚合器")
    parser.add_argument("--test", action="store_true", help="测试模式")
    parser.add_argument("--skip-clustering", action="store_true", help="跳过聚类")
    parser.add_argument("--skip-synthesis", action="store_true", help="跳过情报合成")
    parser.add_argument("--skip-telegram", action="store_true", help="跳过 Telegram")
    parser.add_argument("--skip-twitter", action="store_true", help="跳过 Twitter 抓取")
    parser.add_argument("--twitter-limit", type=int, default=10, help="Twitter KOL 数量限制")
    parser.add_argument("--schedule", action="store_true", help="定时任务模式")
    parser.add_argument("--concurrency", type=int, default=5, help="并发数")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    load_dotenv()
    setup_logging(level=args.log_level)
    logger = get_main_logger()

    if args.schedule:
        asyncio.run(run_scheduler())
    else:
        asyncio.run(run_ainsight(
            test_mode=args.test,
            skip_clustering=args.skip_clustering,
            skip_synthesis=args.skip_synthesis,
            skip_telegram=args.skip_telegram,
            skip_twitter=args.skip_twitter,
            twitter_limit=args.twitter_limit,
            concurrency=args.concurrency,
        ))


if __name__ == "__main__":
    main()
