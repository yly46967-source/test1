"""News Funnel - 新闻信息漏斗工具"""
import asyncio
import argparse
from datetime import datetime
from pathlib import Path
from typing import List

import yaml
from dotenv import load_dotenv

from src.models import NewsItem, NewsSource, Region
from src.fetcher import RSSFetcher
from src.processor import Summarizer, Classifier
from src.notifier import TelegramNotifier


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


async def fetch_all(sources: List[NewsSource], settings: dict) -> List[NewsItem]:
    """从所有源抓取新闻"""
    all_items = []
    max_items = settings.get("max_items_per_source", 10)
    timeout = settings.get("request_timeout", 30)

    for source in sources:
        if source.source_type == "rss":
            fetcher = RSSFetcher(source, max_items=max_items, timeout=timeout)
            items = await fetcher.fetch()
            all_items.extend(items)
            print(f"[{source.name}] 抓取 {len(items)} 条")

    return all_items


async def process_news(items: List[NewsItem]) -> List[NewsItem]:
    """AI 处理新闻（总结 + 分类）"""
    summarizer = Summarizer()
    classifier = Classifier()

    print(f"正在处理 {len(items)} 条新闻...")
    items = await summarizer.summarize_batch(items)
    items = await classifier.classify_batch(items)

    return items


async def send_to_telegram(items: List[NewsItem], title: str):
    """推送到 Telegram"""
    notifier = TelegramNotifier()
    await notifier.send_digest(items, title=title)
    print(f"已推送 {len(items)} 条新闻到 Telegram")


def get_period_name(hour: int) -> str:
    """根据小时获取时段名称"""
    if hour < 10:
        return "早报"
    elif hour < 14:
        return "午报"
    else:
        return "晚报"


async def run(test_mode: bool = False, skip_ai: bool = False, skip_telegram: bool = False):
    """主运行流程"""
    sources, settings = load_sources()
    print(f"已加载 {len(sources)} 个新闻源")

    items = await fetch_all(sources, settings)
    print(f"共抓取 {len(items)} 条新闻")

    if not items:
        print("没有抓取到新闻")
        return

    if test_mode:
        items = items[:3]
        print(f"测试模式：只处理 {len(items)} 条")

    if not skip_ai:
        items = await process_news(items)

    for item in items:
        title = item.title.replace('\xa0', ' ')
        print(f"\n[{item.category.value}] {title}")
        print(f"  来源: {item.source_name} ({item.region.value})")
        if item.summary:
            print(f"  摘要: {item.summary}")

    if not skip_telegram:
        now = datetime.now()
        period = get_period_name(now.hour)
        title = f"📰 {now.strftime('%m月%d日')} {period}"
        await send_to_telegram(items, title)


async def run_scheduler():
    """定时任务调度器 - 北京时间 8:00, 12:00, 21:00"""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    import pytz

    beijing_tz = pytz.timezone('Asia/Shanghai')
    scheduler = AsyncIOScheduler(timezone=beijing_tz)

    async def scheduled_run():
        print(f"\n{'='*50}")
        print(f"定时任务启动: {datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*50}")
        await run()

    # 北京时间 8:00, 12:00, 21:00
    scheduler.add_job(scheduled_run, CronTrigger(hour=8, minute=0, timezone=beijing_tz))
    scheduler.add_job(scheduled_run, CronTrigger(hour=12, minute=0, timezone=beijing_tz))
    scheduler.add_job(scheduled_run, CronTrigger(hour=21, minute=0, timezone=beijing_tz))

    scheduler.start()
    print("定时任务已启动，将在以下时间运行（北京时间）：")
    print("  - 08:00 早报")
    print("  - 12:00 午报")
    print("  - 21:00 晚报")
    print("\n按 Ctrl+C 停止...")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        scheduler.shutdown()
        print("\n定时任务已停止")


def main():
    parser = argparse.ArgumentParser(description="News Funnel - 新闻信息漏斗")
    parser.add_argument("--test", action="store_true", help="测试模式（只处理3条）")
    parser.add_argument("--skip-ai", action="store_true", help="跳过 AI 处理")
    parser.add_argument("--skip-telegram", action="store_true", help="跳过 Telegram 推送")
    parser.add_argument("--schedule", action="store_true", help="启动定时任务模式")
    args = parser.parse_args()

    load_dotenv()

    if args.schedule:
        asyncio.run(run_scheduler())
    else:
        asyncio.run(run(
            test_mode=args.test,
            skip_ai=args.skip_ai,
            skip_telegram=args.skip_telegram
        ))


if __name__ == "__main__":
    main()
