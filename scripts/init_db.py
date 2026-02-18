"""数据库初始化脚本"""
import asyncio
import sys
import os

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from src.database import DatabaseService

load_dotenv()


async def init_database():
    """初始化数据库"""
    # 从环境变量获取数据库URL，默认使用SQLite（开发环境）
    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./news_funnel.db"
    )

    print(f"正在连接数据库: {database_url.split('@')[-1] if '@' in database_url else database_url}")

    db = DatabaseService(database_url)

    try:
        print("正在创建数据库表...")
        await db.init_db()
        print("✅ 数据库表创建成功！")

        # 显示创建的表
        print("\n已创建的表:")
        print("  - news_sources (新闻源)")
        print("  - news_articles (新闻文章)")
        print("  - fetch_logs (抓取日志)")
        print("  - users (用户)")
        print("  - user_subscriptions (用户订阅)")

    except Exception as e:
        print(f"❌ 数据库初始化失败: {e}")
        raise
    finally:
        await db.close()


async def sync_sources_to_db():
    """将 YAML 配置的新闻源同步到数据库"""
    import yaml

    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./news_funnel.db"
    )

    db = DatabaseService(database_url)

    try:
        # 读取 YAML 配置
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config",
            "sources.yaml"
        )

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        sources = config.get("sources", [])
        print(f"\n正在同步 {len(sources)} 个新闻源到数据库...")

        for source in sources:
            if not source.get("enabled", True):
                continue

            await db.upsert_source({
                "name": source["name"],
                "url": source["url"],
                "region": source["region"],
                "source_type": source.get("type", "rss"),
                "enabled": source.get("enabled", True),
            })
            print(f"  ✓ {source['name']}")

        print("✅ 新闻源同步完成！")

    except FileNotFoundError:
        print("⚠️ 未找到 config/sources.yaml，跳过新闻源同步")
    except Exception as e:
        print(f"❌ 新闻源同步失败: {e}")
        raise
    finally:
        await db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("News Funnel 数据库初始化")
    print("=" * 50)

    asyncio.run(init_database())
    asyncio.run(sync_sources_to_db())

    print("\n" + "=" * 50)
    print("初始化完成！")
    print("=" * 50)
