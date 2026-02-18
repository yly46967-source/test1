"""数据库功能测试脚本"""
import asyncio
import sys
import os
from datetime import datetime

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from src.database import DatabaseService
from src.database.models import CategoryEnum, RegionEnum

load_dotenv()


async def test_database():
    """测试数据库各项功能"""
    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./news_funnel.db"
    )

    print("=" * 50)
    print("数据库功能测试")
    print("=" * 50)

    db = DatabaseService(database_url)

    try:
        # 1. 测试新闻源操作
        print("\n[1] 测试新闻源操作...")

        # 插入新闻源
        source = await db.upsert_source({
            "name": "Test Source",
            "url": "https://example.com/rss",
            "region": "world",
            "source_type": "rss",
            "enabled": True,
        })
        print(f"  ✓ 插入新闻源: {source.name} (ID: {source.id})")

        # 获取所有新闻源
        sources = await db.get_all_sources()
        print(f"  ✓ 获取新闻源列表: {len(sources)} 个")

        # 2. 测试文章操作
        print("\n[2] 测试文章操作...")

        # 插入文章
        article_data = {
            "title": "测试新闻标题",
            "url": "https://example.com/news/1",
            "content": "这是测试新闻的内容...",
            "region": "world",
            "source_id": source.id,
            "source_name": source.name,
            "published_at": datetime.utcnow(),
        }
        article = await db.save_article(article_data)
        if article:
            print(f"  ✓ 插入文章: {article.title} (ID: {article.id})")
        else:
            print("  ✓ 文章已存在，跳过插入")

        # 测试去重
        duplicate = await db.save_article(article_data)
        if duplicate is None:
            print("  ✓ 去重功能正常: 重复文章被跳过")

        # 检查文章是否存在
        exists = await db.article_exists("https://example.com/news/1")
        print(f"  ✓ 文章存在检查: {exists}")

        # 获取未处理文章
        unprocessed = await db.get_unprocessed_articles(limit=10)
        print(f"  ✓ 未处理文章: {len(unprocessed)} 篇")

        # 3. 测试文章处理标记
        print("\n[3] 测试文章处理流程...")

        if article:
            # 标记为已处理
            await db.mark_article_processed(
                article.id,
                summary="这是AI生成的摘要",
                category=CategoryEnum.TECH
            )
            print("  ✓ 标记文章已处理")

            # 获取未推送文章
            unsent = await db.get_unsent_articles(limit=10)
            print(f"  ✓ 未推送文章: {len(unsent)} 篇")

            # 标记为已推送
            await db.mark_articles_sent([article.id])
            print("  ✓ 标记文章已推送")

        # 4. 测试抓取日志
        print("\n[4] 测试抓取日志...")

        log = await db.create_fetch_log(
            source_id=source.id,
            status="success",
            items_fetched=10,
            items_new=5,
            duration_ms=1500,
        )
        print(f"  ✓ 创建抓取日志 (ID: {log.id})")

        logs = await db.get_recent_fetch_logs(limit=5)
        print(f"  ✓ 获取最近日志: {len(logs)} 条")

        # 5. 测试统计功能
        print("\n[5] 测试统计功能...")

        stats = await db.get_article_stats()
        print(f"  ✓ 文章统计:")
        print(f"    - 总数: {stats['total']}")
        print(f"    - 今日: {stats['today']}")
        print(f"    - 未处理: {stats['unprocessed']}")
        print(f"    - 未推送: {stats['unsent']}")

        # 6. 测试条件查询
        print("\n[6] 测试条件查询...")

        articles = await db.get_articles_by_filter(
            category=CategoryEnum.TECH,
            limit=5
        )
        print(f"  ✓ 按分类查询: {len(articles)} 篇科技新闻")

        articles = await db.get_articles_by_filter(
            region=RegionEnum.WORLD,
            limit=5
        )
        print(f"  ✓ 按区域查询: {len(articles)} 篇世界新闻")

        print("\n" + "=" * 50)
        print("✅ 所有测试通过！")
        print("=" * 50)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(test_database())
