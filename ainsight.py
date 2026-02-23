"""AInsight MVP - 简化版主程序

流程：抓取 → 硬过滤 → 评分排序 → 主题提取 → 情报生成 → 展示

命令：
    python ainsight.py              # 运行完整流程
    python ainsight.py --web        # 启动 Web 服务
    python ainsight.py --all        # 同时运行流程和 Web
    python ainsight.py --init       # 初始化数据库
"""
import asyncio
import argparse
import sys
import os
import hashlib
from datetime import datetime
from typing import List
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy import select, update

load_dotenv()

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 全局变量
db = None
logger = None


def get_llm_client():
    """获取 LLM 客户端"""
    return AsyncOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


async def init_database():
    """初始化数据库"""
    from src.database import DatabaseService

    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ainsight.db")
    db = DatabaseService(database_url)
    await db.init_db()
    logger.info("数据库已初始化")
    return db


async def import_kols():
    """从配置文件导入 KOL"""
    import yaml
    from src.database.models import KOL

    config_path = "config/kols.yaml"
    if not os.path.exists(config_path):
        logger.warning(f"KOL 配置不存在: {config_path}")
        return 0

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 收集所有 tier 的 KOL
    kols_data = []
    for tier_key in ["god_tier", "expert_tier", "insider_tier", "observer_tier", "chinese_kols"]:
        tier_kols = config.get(tier_key, [])
        if tier_kols:
            kols_data.extend(tier_kols)

    if not kols_data:
        logger.warning("配置文件中没有 KOL 数据")
        return 0

    created = 0
    async with db.async_session() as session:
        for kol_data in kols_data:
            handle = kol_data.get("handle", "").lstrip("@")
            if not handle:
                continue

            # 只导入 X 平台的 KOL
            platform = kol_data.get("platform", "x")
            if platform != "x":
                continue

            existing = await session.execute(
                select(KOL).where(KOL.handle == handle)
            )
            if existing.scalar_one_or_none():
                continue

            kol = KOL(
                handle=handle,
                name=kol_data.get("name") or handle,
                platform="x",
                is_active=True,
            )
            session.add(kol)
            created += 1

        await session.commit()

    logger.info(f"KOL 导入: {created} 新增")
    return created


async def run_fetch(limit: int = 10, profile: str = "Default") -> List[dict]:
    """运行 Twitter 抓取（使用 Chrome Profile + FxTwitter API）

    Args:
        limit: KOL 数量限制
        profile: Chrome Profile 名称 (Default, Profile 2, Profile 3)
    """
    from src.fetcher.chrome_twitter import ChromeTwitterFetcher
    from src.database.models import RawContent, SourceTypeEnum
    from src.algorithms.scoring import calc_value_score, should_filter

    logger.info("=" * 40)
    logger.info("开始抓取 (Chrome Profile + FxTwitter)")
    logger.info("=" * 40)

    kols = await db.get_active_kols(platform="x")
    if not kols:
        logger.warning("没有活跃的 KOL")
        return []

    kols = kols[:limit]
    usernames = [kol.handle for kol in kols if kol.handle]
    kol_map = {kol.handle: kol for kol in kols}

    logger.info(f"抓取 {len(usernames)} 个用户，使用 Profile: {profile}")

    saved = []
    filtered_count = 0

    try:
        async with ChromeTwitterFetcher(
            profile_name=profile,
            headless=False,  # 显示浏览器便于调试
            max_tweets=20,
        ) as fetcher:
            results = await fetcher.fetch_multiple_users(usernames, delay_between=3.0)

        async with db.async_session() as session:
            for username, result in results.items():
                if not result.success:
                    logger.warning(f"@{username}: 失败 - {result.error}")
                    continue

                kol = kol_map.get(username)
                for tweet in result.tweets:
                    if not tweet.tweet_url:
                        continue

                    # 硬过滤
                    text = tweet.text or ""
                    should_drop, reason = should_filter(
                        text,
                        likes=tweet.likes or 0,
                        has_media=bool(tweet.media_urls)
                    )
                    if should_drop:
                        filtered_count += 1
                        continue

                    # URL 去重
                    url_hash = hashlib.sha256(tweet.tweet_url.encode()).hexdigest()
                    existing = await session.execute(
                        select(RawContent.id).where(RawContent.source_url_hash == url_hash)
                    )
                    if existing.scalar_one_or_none():
                        continue

                    # 计算价值评分
                    value_score = calc_value_score(
                        text,
                        likes=tweet.likes or 0,
                        comments=tweet.replies or 0,
                        retweets=tweet.retweets or 0
                    )

                    raw_content = RawContent(
                        source_type=SourceTypeEnum.X_POST,
                        source_url=tweet.tweet_url,
                        source_url_hash=url_hash,
                        kol_id=kol.id if kol else None,
                        author_name=tweet.author_name or (kol.name if kol else tweet.author_handle),
                        author_handle=tweet.author_handle,
                        author_avatar=tweet.author_avatar,
                        is_verified=tweet.is_verified,
                        text_content=text,
                        media_urls=tweet.media_urls or [],
                        likes=tweet.likes,
                        retweets=tweet.retweets,
                        replies=tweet.replies,
                        value_score=value_score,
                        published_at=tweet.published_at,
                        fetched_at=datetime.now(),
                        is_clustered=False,
                        is_synthesized=False,
                    )
                    session.add(raw_content)
                    saved.append({"url": tweet.tweet_url, "score": value_score})

                logger.info(f"@{username}: {len(result.tweets)} 条")

            await session.commit()

        logger.info(f"抓取完成: {len(saved)} 条保存, {filtered_count} 条过滤")

    except Exception as e:
        logger.error(f"抓取失败: {e}")
        import traceback
        traceback.print_exc()

    return saved


async def run_topic_extraction():
    """运行主题提取"""
    from src.database.models import RawContent
    from src.algorithms.topic import extract_topics_batch

    logger.info("=" * 40)
    logger.info("开始主题提取")
    logger.info("=" * 40)

    llm_client = get_llm_client()
    model = os.getenv("DASHSCOPE_MODEL", "qwen-plus")

    async with db.async_session() as session:
        # 获取没有主题的帖子
        query = select(RawContent).where(
            RawContent.topic_name == None,
            RawContent.value_score > 0
        ).order_by(RawContent.value_score.desc()).limit(100)

        result = await session.execute(query)
        posts = result.scalars().all()

        if not posts:
            logger.info("没有待提取主题的帖子")
            return

        logger.info(f"待提取: {len(posts)} 条")

        # 转换为字典
        posts_data = [
            {"text": p.text_content, "id": p.id}
            for p in posts
        ]

        # 批量提取主题
        topic_map = await extract_topics_batch(posts_data, llm_client, model)

        # 更新数据库
        updated = 0
        for i, post in enumerate(posts):
            topics = topic_map.get(i, [])
            if topics:
                post.topic_name = topics[0]  # 取第一个主题
                post.is_clustered = True
                post.clustered_at = datetime.now()
                updated += 1

        await session.commit()

    logger.info(f"主题提取完成: {updated} 条更新")


async def run_intel_generation():
    """运行情报生成"""
    from src.database.models import RawContent, IntelligencePackage
    from src.algorithms.intel import generate_intels_for_topics

    logger.info("=" * 40)
    logger.info("开始情报生成")
    logger.info("=" * 40)

    llm_client = get_llm_client()
    model = os.getenv("DASHSCOPE_MODEL", "qwen-plus")

    async with db.async_session() as session:
        # 获取有主题的帖子
        query = select(RawContent).where(
            RawContent.topic_name != None,
            RawContent.is_synthesized == False
        ).order_by(RawContent.value_score.desc())

        result = await session.execute(query)
        posts = result.scalars().all()

        if not posts:
            logger.info("没有待生成情报的帖子")
            return

        # 按主题分组
        posts_data = [
            {
                "id": p.id,
                "text": p.text_content,
                "author_handle": p.author_handle,
                "author_avatar": p.author_avatar,
                "value_score": p.value_score,
                "topic_name": p.topic_name,
            }
            for p in posts
        ]

        topic_groups = {}
        for p in posts_data:
            topic = p["topic_name"]
            if topic not in topic_groups:
                topic_groups[topic] = []
            topic_groups[topic].append(p)

        logger.info(f"主题分布: {len(topic_groups)} 个主题")

        # 生成情报（只为 >= 2 帖子的主题生成）
        intels = await generate_intels_for_topics(
            topic_groups, llm_client, model, min_posts=2
        )

        # 保存情报
        for intel in intels:
            intel_id = f"intel_{datetime.now().strftime('%Y%m%d')}_{intel.topic[:20]}"

            # 检查是否已存在
            existing = await session.execute(
                select(IntelligencePackage).where(
                    IntelligencePackage.intel_id == intel_id
                )
            )
            if existing.scalar_one_or_none():
                continue

            intel_pkg = IntelligencePackage(
                intel_id=intel_id,
                topic_id=None,  # MVP 不关联 Topic 表
                tldr=intel.title,
                signal=intel.signal,
                shift=intel.shift,
                alpha=intel.alpha,
                source_count=intel.source_count,
                kol_count=len(set(p.get("author_handle") for p in intel.source_posts)),
                is_published=True,
                published_at=datetime.now(),
            )
            session.add(intel_pkg)

            # 标记帖子已合成
            post_ids = [p["id"] for p in intel.source_posts]
            await session.execute(
                update(RawContent)
                .where(RawContent.id.in_(post_ids))
                .values(is_synthesized=True)
            )

        await session.commit()

    logger.info(f"情报生成完成: {len(intels)} 个情报")


async def run_pipeline(limit: int = 10, profile: str = "Default"):
    """运行完整流程"""
    global db

    logger.info("=" * 50)
    logger.info("AInsight MVP 启动")
    logger.info("=" * 50)

    db = await init_database()

    try:
        # 1. 抓取 + 硬过滤 + 评分
        await run_fetch(limit=limit, profile=profile)

        # 2. 主题提取
        await run_topic_extraction()

        # 3. 情报生成
        await run_intel_generation()

        # 统计
        stats = await db.get_clustering_stats()
        logger.info(f"完成: 内容 {stats['raw_contents']['total']}, 情报 {stats['intelligence_packages']['total']}")

    except Exception as e:
        logger.error(f"运行出错: {e}", exc_info=True)
        raise
    finally:
        if db:
            await db.close()


def run_web_server(host: str = "0.0.0.0", port: int = 8001):
    """启动 Web 服务"""
    import uvicorn
    logger.info(f"启动 Web: http://{host}:{port}")
    uvicorn.run("src.web.app:app", host=host, port=port, reload=False)


async def run_all(limit: int = 10, port: int = 8001, profile: str = "Default"):
    """同时运行流程和 Web 服务"""
    global db

    logger.info("=" * 50)
    logger.info("AInsight MVP 全功能模式")
    logger.info("=" * 50)

    db = await init_database()

    # 在后台线程运行 Web 服务
    executor = ThreadPoolExecutor(max_workers=1)
    executor.submit(run_web_server, "0.0.0.0", port)

    logger.info(f"Web 服务已启动: http://localhost:{port}")

    # 运行流程
    try:
        await run_fetch(limit=limit, profile=profile)
        await run_topic_extraction()
        await run_intel_generation()

        logger.info(f"流程完成，Web 服务运行中: http://localhost:{port}")
        logger.info("按 Ctrl+C 退出")

        while True:
            await asyncio.sleep(60)

    except KeyboardInterrupt:
        logger.info("正在退出...")
    finally:
        executor.shutdown(wait=False)
        if db:
            await db.close()


def main():
    global logger, db
    from src.logger import setup_logging, get_main_logger

    parser = argparse.ArgumentParser(description="AInsight MVP")
    parser.add_argument("--web", action="store_true", help="启动 Web 服务")
    parser.add_argument("--all", action="store_true", help="同时运行流程和 Web")
    parser.add_argument("--init", action="store_true", help="初始化数据库")
    parser.add_argument("--limit", type=int, default=10, help="KOL 数量限制")
    parser.add_argument("--port", type=int, default=8001, help="Web 端口")
    parser.add_argument("--profile", type=str, default="Default",
                        help="Chrome Profile 名称 (Default, Profile 2, Profile 3)")
    parser.add_argument("--list-profiles", action="store_true", help="列出可用的 Chrome Profile")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(level=args.log_level)
    logger = get_main_logger()

    # 列出 Chrome Profile
    if args.list_profiles:
        from src.fetcher.chrome_twitter import get_available_profiles
        print("\n可用的 Chrome Profile:")
        for p in get_available_profiles():
            print(f"  --profile \"{p['directory']}\"  # {p['name']} ({p['gaia_name']})")
        print("\n请选择已登录 X 的 Profile")
        return

    if args.web:
        run_web_server(port=args.port)
    elif args.all:
        asyncio.run(run_all(limit=args.limit, port=args.port, profile=args.profile))
    elif args.init:
        async def do_init():
            global db
            db = await init_database()
            await import_kols()
            await db.close()
        asyncio.run(do_init())
    else:
        asyncio.run(run_pipeline(limit=args.limit, profile=args.profile))


if __name__ == "__main__":
    main()
