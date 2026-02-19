"""AInsight - AI 情报聚合器主程序"""
import asyncio
import argparse
import sys
import os
import time
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

from src.fetcher import (
    load_ainsight_sources,
    fetch_ainsight_sources,
    get_enabled_sources,
)
from src.clustering import TopicClusterer, ClusteringPipeline
from src.processor.synthesis_service import SynthesisService
from src.database import DatabaseService
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
    concurrency: int = 5,
):
    """
    AInsight 主运行流程

    流程：
    1. 加载数据源配置
    2. 并发抓取所有源
    3. 聚类处理
    4. 情报合成（≥3 来源触发）
    5. Telegram 推送
    """
    global db

    logger.info("=" * 50)
    logger.info("AInsight 启动")
    logger.info("=" * 50)

    # 初始化数据库
    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ainsight.db")
    db = DatabaseService(database_url)
    await db.init_db()

    # 初始化 FTS 表
    try:
        await db.init_fts_tables()
    except Exception as e:
        logger.warning(f"FTS 初始化跳过: {e}")

    logger.info("数据库已连接")

    try:
        # 1. 加载数据源
        config = load_ainsight_sources()
        sources = get_enabled_sources(config)
        logger.info(f"已加载 {len(sources)} 个数据源")

        # 2. 抓取数据
        start_time = time.time()
        items, stats = await fetch_ainsight_sources(
            sources,
            config.settings,
        )
        elapsed = time.time() - start_time

        logger.info(
            f"抓取完成: {stats['success']} 成功, {stats['failed']} 失败, "
            f"{stats['total_items']} 条内容, 耗时 {elapsed:.1f}s"
        )

        if not items:
            logger.warning("没有抓取到内容")
            return

        if test_mode:
            items = items[:5]
            logger.info(f"测试模式: 只处理 {len(items)} 条")

        # 3. 聚类处理
        if not skip_clustering:
            await run_clustering(items)
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
        logger.info(f"统计: 主题 {clustering_stats['topics']['active']} 个, "
                   f"内容 {clustering_stats['raw_contents']['total']} 条, "
                   f"情报包 {clustering_stats['intelligence_packages']['total']} 个")

        logger.info("运行完成")

    except Exception as e:
        logger.error(f"运行出错: {e}", exc_info=True)
        raise
    finally:
        if db:
            await db.close()


async def run_clustering(items):
    """运行聚类流水线"""
    logger.info(f"开始聚类处理 {len(items)} 条内容...")

    # 初始化 LLM 客户端
    llm_client = AsyncOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    # 初始化聚类器
    clusterer = TopicClusterer(
        llm_client=llm_client,
        model=os.getenv("LLM_MODEL", "qwen-plus"),
    )

    # 处理每条内容
    async with db.session() as session:
        pipeline = ClusteringPipeline(session, clusterer)

        processed = 0
        skipped = 0

        for item in items:
            try:
                # 转换为聚类流水线格式
                content = {
                    "text": item.text,
                    "source_type": item.source_type,
                    "source_url": item.source_url,
                    "title": item.title,
                    "published_at": item.published_at,
                    "kol_name": item.kol_name,
                    "kol_handle": item.kol_handle,
                    "metrics": item.metrics,
                    "media_urls": item.media_urls,
                    "raw_data": item.raw_data,
                }

                topic_id = await pipeline.process_content(content)
                if topic_id:
                    processed += 1
                else:
                    skipped += 1

            except Exception as e:
                logger.warning(f"处理内容失败: {e}")
                skipped += 1

        await session.commit()

    logger.info(f"聚类完成: {processed} 处理, {skipped} 跳过")


async def run_synthesis():
    """运行情报合成"""
    logger.info("检查情报合成触发条件...")

    # 初始化 LLM 客户端
    llm_client = AsyncOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    from src.processor.synthesis import SynthesisEngine

    engine = SynthesisEngine(
        llm_client=llm_client,
        model=os.getenv("LLM_MODEL", "qwen-plus"),
    )

    async with db.session() as session:
        synthesis_service = SynthesisService(
            session=session,
            engine=engine,
        )

        result = await synthesis_service.synthesize_all_pending()
        logger.info(f"情报合成: {result.get('success', 0)} 个主题, {result.get('skipped', 0)} 跳过")


async def send_intelligence_digest():
    """发送情报摘要到 Telegram"""
    logger.info("准备发送情报摘要...")

    notifier = TelegramNotifier()

    # 获取统计数据
    stats = await db.get_clustering_stats()

    # 获取热门主题
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

    # 发送每日摘要
    daily_stats = {
        "new_contents": stats["raw_contents"]["total"],
        "active_topics": stats["topics"]["active"],
        "intel_packages": stats["intelligence_packages"]["total"],
    }

    await notifier.send_daily_digest(daily_stats, topics_data)

    # 获取已发布的情报包
    intel_packages = await db.get_published_intelligence(limit=3)

    for intel in intel_packages:
        topic = await db.get_topic_by_id(intel.topic_id)
        if not topic:
            continue

        intel_data = {
            "tldr": intel.tldr,
            "fact_summary": intel.fact_summary,
            "action_guide": intel.action_guide,
            "verdict": intel.verdict,
        }

        await notifier.send_intelligence(
            topic_title=topic.title,
            category=topic.category.value if topic.category else "news",
            intel_data=intel_data,
            source_count=intel.source_count,
            heat_score=topic.heat_score,
        )
        logger.info(f"已推送情报: {topic.title}")

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

    # 北京时间 8:00, 12:00, 21:00
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
    parser.add_argument("--test", action="store_true", help="测试模式（只处理5条）")
    parser.add_argument("--skip-clustering", action="store_true", help="跳过聚类")
    parser.add_argument("--skip-synthesis", action="store_true", help="跳过情报合成")
    parser.add_argument("--skip-telegram", action="store_true", help="跳过 Telegram")
    parser.add_argument("--schedule", action="store_true", help="定时任务模式")
    parser.add_argument("--concurrency", type=int, default=5, help="并发数")
    parser.add_argument("--log-level", default="INFO",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"])
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
            concurrency=args.concurrency,
        ))


if __name__ == "__main__":
    main()
