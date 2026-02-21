"""AInsight 完整流水线运行脚本
从数据库 KOL 表读取 RSS 源，抓取内容，聚类，合成情报
"""
import asyncio
import sys
import os
import time
from datetime import datetime
from typing import List, Optional, Dict, Any

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import feedparser
import httpx

from src.database.models import KOL, RawContent, Topic, SourceTypeEnum
from src.database.service import DatabaseService
from src.logger import setup_logging, get_main_logger

load_dotenv()


class RSSPipeline:
    """RSS 抓取流水线"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self.logger = get_main_logger()
        self.stats = {
            "kols_processed": 0,
            "items_fetched": 0,
            "items_saved": 0,
            "items_skipped": 0,
            "errors": 0,
        }

    async def close(self):
        await self.engine.dispose()

    async def get_active_kols_with_rss(self) -> List[KOL]:
        """获取所有有 RSS URL 的活跃 KOL"""
        async with self.async_session() as session:
            result = await session.execute(
                select(KOL).where(
                    KOL.is_active == True,
                    KOL.rss_url != None,
                    KOL.rss_url != "",
                )
            )
            return result.scalars().all()

    async def fetch_rss(self, url: str, kol_name: str) -> Optional[List[Dict]]:
        """抓取 RSS 内容"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "AInsight/1.0 (RSS Reader)"},
                    follow_redirects=True,
                )
                response.raise_for_status()

                feed = feedparser.parse(response.text)
                if not feed.entries:
                    return None

                items = []
                for entry in feed.entries[:10]:  # 每个源最多 10 条
                    items.append({
                        "title": entry.get("title", ""),
                        "link": entry.get("link", ""),
                        "summary": entry.get("summary", ""),
                        "content": entry.get("content", [{}])[0].get("value", "") if entry.get("content") else "",
                        "published": entry.get("published_parsed"),
                    })
                return items

        except Exception as e:
            self.logger.warning(f"[{kol_name}] RSS 抓取失败: {e}")
            return None

    async def save_content(
        self,
        session: AsyncSession,
        kol: KOL,
        item: Dict
    ) -> bool:
        """保存内容到数据库"""
        import hashlib

        link = item.get("link", "")
        if not link:
            return False

        # 计算 URL hash
        url_hash = hashlib.sha256(link.encode()).hexdigest()

        # 检查是否已存在
        existing = await session.execute(
            select(RawContent).where(RawContent.source_url_hash == url_hash)
        )
        if existing.scalar_one_or_none():
            return False

        # 构建内容
        title = item.get("title", "")
        content = item.get("content") or item.get("summary", "")
        text = f"{title}\n\n{content}" if title else content

        # 解析发布时间
        published_at = None
        if item.get("published"):
            try:
                published_at = datetime(*item["published"][:6])
            except:
                pass

        # 创建 RawContent
        raw_content = RawContent(
            source_type=SourceTypeEnum.BLOG_POST if kol.platform == "blog" else SourceTypeEnum.X_POST,
            source_url=link,
            source_url_hash=url_hash,
            kol_id=kol.id,
            title=title,
            text_content=text[:10000],  # 限制长度
            published_at=published_at or datetime.now(),
            is_clustered=False,
            is_synthesized=False,
        )

        session.add(raw_content)
        return True

    async def run_fetch(self, limit: int = 0, platform: str = None):
        """运行抓取流程"""
        self.logger.info("=" * 60)
        self.logger.info("AInsight RSS 抓取流水线")
        self.logger.info("=" * 60)

        # 获取 KOL 列表
        kols = await self.get_active_kols_with_rss()

        # 过滤平台
        if platform:
            kols = [k for k in kols if k.platform == platform]

        if limit > 0:
            kols = kols[:limit]

        self.logger.info(f"待抓取 KOL: {len(kols)} 个")

        # 并发抓取
        semaphore = asyncio.Semaphore(10)  # 并发数

        async def fetch_kol(kol: KOL):
            async with semaphore:
                items = await self.fetch_rss(kol.rss_url, kol.name)
                return kol, items

        start_time = time.time()
        tasks = [fetch_kol(kol) for kol in kols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 保存结果
        async with self.async_session() as session:
            for result in results:
                if isinstance(result, Exception):
                    self.stats["errors"] += 1
                    continue

                kol, items = result
                self.stats["kols_processed"] += 1

                if not items:
                    continue

                self.stats["items_fetched"] += len(items)

                for item in items:
                    saved = await self.save_content(session, kol, item)
                    if saved:
                        self.stats["items_saved"] += 1
                    else:
                        self.stats["items_skipped"] += 1

            await session.commit()

        elapsed = time.time() - start_time

        # 输出统计
        self.logger.info("-" * 60)
        self.logger.info("抓取统计:")
        self.logger.info(f"  KOL 处理: {self.stats['kols_processed']}")
        self.logger.info(f"  内容抓取: {self.stats['items_fetched']}")
        self.logger.info(f"  新增保存: {self.stats['items_saved']}")
        self.logger.info(f"  跳过重复: {self.stats['items_skipped']}")
        self.logger.info(f"  错误: {self.stats['errors']}")
        self.logger.info(f"  耗时: {elapsed:.1f}s")
        self.logger.info("=" * 60)

        return self.stats


async def run_clustering(db: DatabaseService):
    """运行聚类流程 - 直接为已有内容创建/匹配主题"""
    logger = get_main_logger()
    logger.info("=" * 60)
    logger.info("内容聚类处理")
    logger.info("=" * 60)

    try:
        from openai import AsyncOpenAI
        from src.clustering.topic_cluster import TopicClusterer, ClusterAction
        from src.database.models import Topic, TopicStatusEnum, IntelCategoryEnum
        import re

        # 初始化 LLM
        api_key = os.getenv("DASHSCOPE_API_KEY")
        base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        model = os.getenv("DASHSCOPE_MODEL", "qwen-plus")

        logger.info(f"LLM 配置: model={model}")

        llm_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

        clusterer = TopicClusterer(
            llm_client=llm_client,
            model=model,
        )

        async with db.session() as session:
            # 获取未聚类的内容
            result = await session.execute(
                select(RawContent).where(RawContent.is_clustered == False).limit(20)
            )
            contents = result.scalars().all()

            if not contents:
                logger.info("没有待聚类的内容")
                return

            logger.info(f"待聚类内容: {len(contents)} 条")

            processed = 0
            errors = 0

            for i, content in enumerate(contents):
                try:
                    title = content.title[:50] if content.title else 'No title'
                    logger.info(f"[{i+1}/{len(contents)}] {title}...")

                    content_dict = {
                        "text": content.text_content[:2000],
                        "source_type": content.source_type.value,
                        "source_url": content.source_url,
                        "title": content.title,
                    }

                    # 获取已有主题作为候选
                    topics_result = await session.execute(
                        select(Topic).where(Topic.status == TopicStatusEnum.ACTIVE).limit(10)
                    )
                    existing_topics = topics_result.scalars().all()

                    candidates = [
                        {
                            "id": t.id,
                            "title": t.title,
                            "category": t.category.value if t.category else "news",
                            "keywords": t.keywords or "",
                            "heat_score": t.heat_score,
                        }
                        for t in existing_topics
                    ]

                    # 调用 LLM 聚类
                    result = await clusterer.cluster(content_dict, candidates)
                    logger.info(f"  决策: {result.action.value}, 相关度: {result.relevance_score:.2f}")

                    topic_id = None

                    if result.action == ClusterAction.MERGE and result.topic_id:
                        topic_id = result.topic_id
                        # 更新主题热度
                        topic = await session.get(Topic, topic_id)
                        if topic:
                            topic.source_count += 1
                            topic.heat_score = min(100, topic.heat_score + 5)

                    elif result.action == ClusterAction.CREATE:
                        # 创建新主题 - 使用 LLM 生成主题信息或使用默认值
                        if result.new_topic:
                            new_topic = result.new_topic
                        else:
                            # 如果 LLM 没有返回 new_topic，使用内容标题创建
                            new_topic = {
                                "title": content.title or "New Topic",
                                "category": "research",
                                "tags": [],
                                "keywords": "",
                            }

                        slug = re.sub(r'[^\w\-]', '-', new_topic.get("title", "topic")[:50].lower())
                        slug = f"{slug}-{int(datetime.now().timestamp())}"

                        category_str = new_topic.get("category", "research")
                        try:
                            category = IntelCategoryEnum(category_str)
                        except:
                            category = IntelCategoryEnum.RESEARCH

                        topic = Topic(
                            title=new_topic.get("title", content.title or "New Topic"),
                            slug=slug,
                            description=content.text_content[:500],
                            keywords=new_topic.get("keywords", ""),
                            category=category,
                            tags=new_topic.get("tags", []),
                            heat_score=10,
                            source_count=1,
                            status=TopicStatusEnum.ACTIVE,
                            first_seen_at=datetime.now(),
                        )
                        session.add(topic)
                        await session.flush()
                        topic_id = topic.id
                        logger.info(f"  创建新主题: {topic.title}")

                    # 如果是 REVIEW 决策，也创建新主题（不要丢弃内容）
                    if topic_id is None and result.action == ClusterAction.REVIEW:
                        # REVIEW 也创建主题，只是标记为需要审核
                        new_topic = {
                            "title": content.title or "Pending Review",
                            "category": "research",
                            "tags": ["review"],
                            "keywords": "",
                        }

                        slug = re.sub(r'[^\w\-]', '-', new_topic.get("title", "topic")[:50].lower())
                        slug = f"{slug}-{int(datetime.now().timestamp())}"

                        topic = Topic(
                            title=new_topic.get("title"),
                            slug=slug,
                            description=content.text_content[:500],
                            keywords="",
                            category=IntelCategoryEnum.RESEARCH,
                            tags=["review"],
                            heat_score=5,
                            source_count=1,
                            status=TopicStatusEnum.ACTIVE,
                            first_seen_at=datetime.now(),
                        )
                        session.add(topic)
                        await session.flush()
                        topic_id = topic.id
                        logger.info(f"  创建待审核主题: {topic.title}")

                    # 更新内容 - 所有内容都必须关联主题
                    content.is_clustered = True
                    if topic_id:
                        content.topic_id = topic_id
                        content.relevance_score = result.relevance_score
                        processed += 1
                        logger.info(f"  -> 关联到主题 #{topic_id}")
                    else:
                        logger.warning(f"  -> 未能关联主题")

                except Exception as e:
                    errors += 1
                    logger.warning(f"  -> 聚类失败: {e}")

            await session.commit()
            logger.info(f"聚类完成: {processed} 成功关联, {errors} 失败")

    except ImportError as e:
        logger.warning(f"聚类模块导入失败: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        logger.error(f"聚类出错: {e}")
        import traceback
        traceback.print_exc()


async def run_synthesis(db: DatabaseService):
    """运行情报合成"""
    logger = get_main_logger()
    logger.info("=" * 60)
    logger.info("情报合成处理")
    logger.info("=" * 60)

    try:
        from openai import AsyncOpenAI
        from src.processor.synthesis import SynthesisEngine
        from src.processor.synthesis_service import SynthesisService

        llm_client = AsyncOpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        engine = SynthesisEngine(
            llm_client=llm_client,
            model=os.getenv("LLM_MODEL", "qwen-plus"),
        )

        async with db.session() as session:
            service = SynthesisService(session=session, engine=engine)
            result = await service.synthesize_all_pending()
            logger.info(f"合成完成: {result.get('success', 0)} 个主题")

    except ImportError as e:
        logger.warning(f"合成模块导入失败: {e}")
    except Exception as e:
        logger.error(f"合成出错: {e}")


async def show_stats(db: DatabaseService):
    """显示数据库统计"""
    logger = get_main_logger()

    stats = await db.get_clustering_stats()

    logger.info("=" * 60)
    logger.info("数据库统计")
    logger.info("=" * 60)
    logger.info(f"  KOL: {stats.get('kols', {}).get('total', 0)} 个")
    logger.info(f"  原始内容: {stats.get('raw_contents', {}).get('total', 0)} 条")
    logger.info(f"  主题: {stats.get('topics', {}).get('active', 0)} 个")
    logger.info(f"  情报包: {stats.get('intelligence_packages', {}).get('total', 0)} 个")
    logger.info("=" * 60)


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="AInsight 流水线运行")
    parser.add_argument("--fetch", action="store_true", help="运行 RSS 抓取")
    parser.add_argument("--cluster", action="store_true", help="运行聚类")
    parser.add_argument("--synthesize", action="store_true", help="运行情报合成")
    parser.add_argument("--all", action="store_true", help="运行完整流水线")
    parser.add_argument("--stats", action="store_true", help="显示统计")
    parser.add_argument("--limit", type=int, default=0, help="限制 KOL 数量")
    parser.add_argument("--platform", type=str, help="过滤平台 (blog/x)")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    args = parser.parse_args()

    setup_logging(level=args.log_level)
    logger = get_main_logger()

    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ainsight.db")
    logger.info(f"数据库: {database_url}")

    # 初始化数据库服务
    db = DatabaseService(database_url)
    await db.init_db()

    try:
        if args.stats or (not args.fetch and not args.cluster and not args.synthesize and not args.all):
            await show_stats(db)

        if args.fetch or args.all:
            pipeline = RSSPipeline(database_url)
            try:
                await pipeline.run_fetch(limit=args.limit, platform=args.platform)
            finally:
                await pipeline.close()

        if args.cluster or args.all:
            await run_clustering(db)

        if args.synthesize or args.all:
            await run_synthesis(db)

        if args.all:
            await show_stats(db)

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
