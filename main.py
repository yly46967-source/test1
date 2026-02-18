"""News Funnel - 新闻信息漏斗工具"""
import asyncio
import argparse
import sys
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import yaml
from dotenv import load_dotenv

from src.models import NewsItem, NewsSource, Region
from src.fetcher import RSSFetcher
from src.processor import Summarizer, Classifier
from src.notifier import TelegramNotifier
from src.database import DatabaseService
from src.database.models import CategoryEnum, RegionEnum
from src.logger import setup_logging, get_main_logger
from src.utils import gather_with_concurrency

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


# 全局变量
db: Optional[DatabaseService] = None
logger = None

# 并发配置
DEFAULT_CONCURRENCY = 5  # 默认并发数


def load_sources(config_path: str = "config/sources.yaml") -> List[NewsSource]:
    """加载新闻源配置"""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    sources = []
    settings = config.get("settings", {})

    for item in config.get("china", []):
        if item.get("enabled", True):
            sources.append(NewsSource(
                name=item["name"],
                url=item["url"],
                region=Region.CHINA,
                source_type=item.get("type", "rss")
            ))

    for item in config.get("world", []):
        if item.get("enabled", True):
            sources.append(NewsSource(
                name=item["name"],
                url=item["url"],
                region=Region.WORLD,
                source_type=item.get("type", "rss")
            ))

    return sources, settings


async def fetch_all(
    sources: List[NewsSource],
    settings: dict,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> List[NewsItem]:
    """
    从所有源并发抓取新闻

    Args:
        sources: 新闻源列表
        settings: 配置
        concurrency: 最大并发数

    Returns:
        所有抓取到的新闻列表
    """
    max_items = settings.get("max_items_per_source", 10)
    timeout = settings.get("request_timeout", 30)

    # 创建所有抓取任务
    async def fetch_source(source: NewsSource) -> Tuple[str, List[NewsItem]]:
        """抓取单个源并返回结果"""
        if source.source_type != "rss":
            return source.name, []

        fetcher = RSSFetcher(source, max_items=max_items, timeout=timeout)
        items = await fetcher.fetch()
        return source.name, items

    # 记录开始时间
    start_time = time.time()

    # 并发执行所有抓取任务
    logger.info(f"开始并发抓取 (并发数: {concurrency})...")
    tasks = [fetch_source(source) for source in sources]
    results = await gather_with_concurrency(concurrency, *tasks)

    # 处理结果
    all_items = []
    success_count = 0
    fail_count = 0

    for result in results:
        if isinstance(result, Exception):
            fail_count += 1
            logger.error(f"抓取异常: {result}")
        else:
            source_name, items = result
            if items:
                all_items.extend(items)
                success_count += 1
                logger.info(f"[{source_name}] 抓取 {len(items)} 条")
            else:
                fail_count += 1
                logger.warning(f"[{source_name}] 抓取 0 条")

    # 统计耗时
    elapsed = time.time() - start_time
    logger.info(
        f"抓取完成: {success_count} 成功, {fail_count} 失败, "
        f"耗时 {elapsed:.1f}s"
    )

    return all_items


async def save_to_database(items: List[NewsItem]) -> List[NewsItem]:
    """保存新闻到数据库，返回新增的新闻（去重后）"""
    if db is None:
        return items

    new_items = []
    skipped = 0

    # 先确保新闻源存在于数据库
    source_cache = {}

    for item in items:
        # 检查是否已存在
        if await db.article_exists(item.url):
            skipped += 1
            continue

        # 获取或创建新闻源
        if item.source_name not in source_cache:
            source = await db.get_source_by_name(item.source_name)
            if source is None:
                # 创建新闻源
                await db.upsert_source({
                    "name": item.source_name,
                    "url": "",  # RSS URL 未知
                    "region": item.region.value.lower() if item.region == Region.CHINA else "world",
                    "source_type": "rss",
                    "enabled": True,
                })
                source = await db.get_source_by_name(item.source_name)
                logger.debug(f"创建新闻源: {item.source_name}")
            source_cache[item.source_name] = source

        source = source_cache[item.source_name]

        # 保存文章
        article_data = {
            "title": item.title,
            "url": item.url,
            "content": item.content,
            "region": "china" if item.region == Region.CHINA else "world",
            "source_id": source.id,
            "source_name": item.source_name,
            "published_at": item.published_at,
        }

        result = await db.save_article(article_data)
        if result:
            new_items.append(item)

    if skipped > 0:
        logger.info(f"去重: 跳过 {skipped} 条已存在的新闻")

    return new_items


async def process_news(items: List[NewsItem]) -> List[NewsItem]:
    """AI 处理新闻（总结 + 分类）"""
    summarizer = Summarizer()
    classifier = Classifier()

    logger.info(f"开始 AI 处理 {len(items)} 条新闻...")
    items = await summarizer.summarize_batch(items)
    items = await classifier.classify_batch(items)
    logger.info("AI 处理完成")

    return items


async def send_to_telegram(items: List[NewsItem], title: str):
    """推送到 Telegram"""
    notifier = TelegramNotifier()
    await notifier.send_digest(items, title=title)
    logger.info(f"已推送 {len(items)} 条新闻到 Telegram")


def get_period_name(hour: int) -> str:
    """根据小时获取时段名称"""
    if hour < 10:
        return "早报"
    elif hour < 14:
        return "午报"
    else:
        return "晚报"


async def run(
    test_mode: bool = False,
    skip_ai: bool = False,
    skip_telegram: bool = False,
    use_db: bool = True,
    concurrency: int = DEFAULT_CONCURRENCY,
):
    """主运行流程"""
    global db

    logger.info("=" * 40)
    logger.info("News Funnel 启动")
    logger.info("=" * 40)

    # 初始化数据库
    if use_db:
        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./news_funnel.db")
        db = DatabaseService(database_url)
        await db.init_db()
        logger.info("数据库已连接")

    try:
        sources, settings = load_sources()
        logger.info(f"已加载 {len(sources)} 个新闻源")

        items = await fetch_all(sources, settings, concurrency=concurrency)
        logger.info(f"共抓取 {len(items)} 条新闻")

        if not items:
            logger.warning("没有抓取到新闻")
            return

        # 保存到数据库并去重
        if use_db and db:
            items = await save_to_database(items)
            logger.info(f"新增 {len(items)} 条新闻")

            if not items:
                logger.info("没有新的新闻需要处理")
                return

        if test_mode:
            items = items[:3]
            logger.info(f"测试模式: 只处理 {len(items)} 条")

        if not skip_ai:
            items = await process_news(items)

        # 输出处理结果
        for item in items:
            title = item.title.replace('\xa0', ' ')
            logger.debug(f"[{item.category.value}] {title} - {item.source_name}")

        if not skip_telegram:
            now = datetime.now()
            period = get_period_name(now.hour)
            title = f"📰 {now.strftime('%m月%d日')} {period}"
            await send_to_telegram(items, title)

        # 显示统计
        if use_db and db:
            stats = await db.get_article_stats()
            logger.info(f"数据库统计: 总计 {stats['total']} 篇, 今日 {stats['today']} 篇")

        logger.info("运行完成")

    except Exception as e:
        logger.error(f"运行出错: {e}", exc_info=True)
        raise
    finally:
        if db:
            await db.close()
            logger.debug("数据库连接已关闭")


async def run_scheduler():
    """定时任务调度器 - 北京时间 8:00, 12:00, 21:00"""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    import pytz

    beijing_tz = pytz.timezone('Asia/Shanghai')
    scheduler = AsyncIOScheduler(timezone=beijing_tz)

    async def scheduled_run():
        logger.info("=" * 50)
        logger.info(f"定时任务启动: {datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 50)
        await run()

    # 北京时间 8:00, 12:00, 21:00
    scheduler.add_job(scheduled_run, CronTrigger(hour=8, minute=0, timezone=beijing_tz))
    scheduler.add_job(scheduled_run, CronTrigger(hour=12, minute=0, timezone=beijing_tz))
    scheduler.add_job(scheduled_run, CronTrigger(hour=21, minute=0, timezone=beijing_tz))

    scheduler.start()
    logger.info("定时任务已启动，将在以下时间运行（北京时间）：")
    logger.info("  - 08:00 早报")
    logger.info("  - 12:00 午报")
    logger.info("  - 21:00 晚报")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info("定时任务已停止")


def main():
    global logger

    parser = argparse.ArgumentParser(description="News Funnel - 新闻信息漏斗")
    parser.add_argument("--test", action="store_true", help="测试模式（只处理3条）")
    parser.add_argument("--skip-ai", action="store_true", help="跳过 AI 处理")
    parser.add_argument("--skip-telegram", action="store_true", help="跳过 Telegram 推送")
    parser.add_argument("--skip-db", action="store_true", help="跳过数据库（不保存、不去重）")
    parser.add_argument("--schedule", action="store_true", help="启动定时任务模式")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                        help=f"并发抓取数 (默认: {DEFAULT_CONCURRENCY})")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别 (默认: INFO)")
    parser.add_argument("--no-log-file", action="store_true", help="不输出日志到文件")
    args = parser.parse_args()

    load_dotenv()

    # 初始化日志系统
    setup_logging(
        level=args.log_level,
        log_to_file=not args.no_log_file,
    )
    logger = get_main_logger()

    if args.schedule:
        asyncio.run(run_scheduler())
    else:
        asyncio.run(run(
            test_mode=args.test,
            skip_ai=args.skip_ai,
            skip_telegram=args.skip_telegram,
            use_db=not args.skip_db,
            concurrency=args.concurrency,
        ))


if __name__ == "__main__":
    main()
