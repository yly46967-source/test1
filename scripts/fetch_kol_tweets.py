"""KOL 推文抓取脚本 - 从数据库读取 KOL 并抓取推文"""
import asyncio
import sys
import os
from datetime import datetime

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database.models import KOL, KOLTierEnum
from src.fetcher.twitter_fetcher import TwitterFetcher, fetch_twitter_kols
from src.fetcher.nitter_gateway import get_nitter_gateway, reset_nitter_gateway

load_dotenv()


async def fetch_kol_tweets(
    tier_filter: str = None,
    limit: int = 50,
    concurrency: int = 3,
    rsshub_url: str = None,
):
    """
    从数据库读取 KOL 并抓取推文

    Args:
        tier_filter: 等级过滤 (god/expert/insider/observer)
        limit: 最大 KOL 数量
        concurrency: 并发数
        rsshub_url: RSSHub 实例 URL（可选）
    """
    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./ainsight.db"
    )

    print("=" * 60)
    print("AInsight Pro - KOL 推文抓取")
    print("=" * 60)
    print(f"数据库: {database_url}")
    print(f"并发数: {concurrency}")
    if tier_filter:
        print(f"等级过滤: {tier_filter}")
    print("-" * 60)

    # 配置网关
    reset_nitter_gateway()  # 重置单例
    gateway = get_nitter_gateway()

    # 如果提供了 RSSHub URL，添加到网关
    if rsshub_url:
        gateway.add_rsshub_instance(rsshub_url)
        gateway.set_prefer_rsshub(True)
        print(f"使用 RSSHub: {rsshub_url}")

    # 连接数据库
    engine = create_async_engine(database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 构建查询
        query = select(KOL).where(KOL.is_active == True).where(KOL.platform == "x")

        if tier_filter:
            tier_map = {
                "god": KOLTierEnum.GOD,
                "expert": KOLTierEnum.EXPERT,
                "insider": KOLTierEnum.INSIDER,
                "observer": KOLTierEnum.OBSERVER,
            }
            if tier_filter.lower() in tier_map:
                query = query.where(KOL.tier == tier_map[tier_filter.lower()])

        query = query.order_by(KOL.weight.desc()).limit(limit)

        result = await session.execute(query)
        kols = list(result.scalars().all())

        if not kols:
            print("没有找到符合条件的 KOL")
            return

        print(f"找到 {len(kols)} 个 KOL")
        print("-" * 60)

        # 抓取推文
        raw_items, stats = await fetch_twitter_kols(
            kols,
            concurrency=concurrency,
            with_replies=False,
        )

        # 更新 KOL 的最后抓取时间
        for kol in kols:
            await session.execute(
                update(KOL)
                .where(KOL.id == kol.id)
                .values(last_fetched_at=datetime.utcnow())
            )
        await session.commit()

    await engine.dispose()

    # 显示结果
    print("\n" + "=" * 60)
    print("抓取统计:")
    print(f"  成功: {stats['success']} 个 KOL")
    print(f"  失败: {stats['failed']} 个 KOL")
    print(f"  总推文: {stats['total_items']} 条")
    print("=" * 60)

    # 显示网关统计
    print("\nNitter 实例统计:")
    for url, stat in gateway.get_stats().items():
        if stat['success'] > 0 or stat['fail'] > 0:
            print(f"  {url}:")
            print(f"    成功/失败: {stat['success']}/{stat['fail']}, 评分: {stat['score']}")

    # 显示部分内容
    if raw_items:
        print(f"\n最新 {min(5, len(raw_items))} 条推文:")
        print("-" * 60)
        for item in raw_items[:5]:
            print(f"[@{item.kol_handle}] {item.text[:100]}...")
            print(f"  URL: {item.source_url}")
            print()

    return raw_items, stats


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="KOL 推文抓取")
    parser.add_argument("--tier", "-t", type=str, help="等级过滤 (god/expert/insider/observer)")
    parser.add_argument("--limit", "-l", type=int, default=10, help="最大 KOL 数量")
    parser.add_argument("--concurrency", "-c", type=int, default=3, help="并发数")
    parser.add_argument("--rsshub", "-r", type=str, help="RSSHub 实例 URL")

    args = parser.parse_args()

    await fetch_kol_tweets(
        tier_filter=args.tier,
        limit=args.limit,
        concurrency=args.concurrency,
        rsshub_url=args.rsshub,
    )


if __name__ == "__main__":
    asyncio.run(main())
