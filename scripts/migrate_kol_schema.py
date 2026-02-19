"""KOL Schema 迁移脚本 - 添加 role, category, weight, rss_url 字段"""
import asyncio
import sys
import os

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()


async def migrate_kol_schema():
    """迁移 KOL 表 Schema"""
    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./ainsight.db"
    )

    print(f"正在连接数据库: {database_url}")
    engine = create_async_engine(database_url, echo=False)

    migrations = [
        # 添加 role 字段
        {
            "name": "添加 role 字段",
            "check": "SELECT COUNT(*) FROM pragma_table_info('kols') WHERE name='role'",
            "sql": "ALTER TABLE kols ADD COLUMN role VARCHAR(20) DEFAULT 'influencer'"
        },
        # 添加 category 字段
        {
            "name": "添加 category 字段",
            "check": "SELECT COUNT(*) FROM pragma_table_info('kols') WHERE name='category'",
            "sql": "ALTER TABLE kols ADD COLUMN category VARCHAR(20) DEFAULT 'general'"
        },
        # 添加 weight 字段
        {
            "name": "添加 weight 字段",
            "check": "SELECT COUNT(*) FROM pragma_table_info('kols') WHERE name='weight'",
            "sql": "ALTER TABLE kols ADD COLUMN weight FLOAT DEFAULT 1.0"
        },
        # 添加 rss_url 字段
        {
            "name": "添加 rss_url 字段",
            "check": "SELECT COUNT(*) FROM pragma_table_info('kols') WHERE name='rss_url'",
            "sql": "ALTER TABLE kols ADD COLUMN rss_url VARCHAR(500)"
        },
    ]

    try:
        async with engine.begin() as conn:
            # 检查 kols 表是否存在
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='kols'")
            )
            if not result.fetchone():
                print("⚠️ kols 表不存在，请先运行 init_db.py 初始化数据库")
                return

            print("\n开始迁移 KOL Schema...")
            print("-" * 50)

            for migration in migrations:
                # 检查字段是否已存在
                check_result = await conn.execute(text(migration["check"]))
                exists = check_result.scalar() > 0

                if exists:
                    print(f"  ⏭️  {migration['name']} - 已存在，跳过")
                else:
                    await conn.execute(text(migration["sql"]))
                    print(f"  ✅ {migration['name']} - 完成")

            print("-" * 50)
            print("✅ KOL Schema 迁移完成！")

            # 显示当前表结构
            print("\n当前 kols 表结构:")
            result = await conn.execute(text("PRAGMA table_info(kols)"))
            columns = result.fetchall()
            for col in columns:
                print(f"  - {col[1]}: {col[2]} (default: {col[4]})")

    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        raise
    finally:
        await engine.dispose()


async def create_indexes():
    """创建新字段的索引"""
    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./ainsight.db"
    )

    engine = create_async_engine(database_url, echo=False)

    indexes = [
        ("idx_kols_role", "CREATE INDEX IF NOT EXISTS idx_kols_role ON kols(role)"),
        ("idx_kols_category", "CREATE INDEX IF NOT EXISTS idx_kols_category ON kols(category)"),
    ]

    try:
        async with engine.begin() as conn:
            print("\n创建索引...")
            for name, sql in indexes:
                await conn.execute(text(sql))
                print(f"  ✅ {name}")
            print("✅ 索引创建完成！")
    except Exception as e:
        print(f"❌ 索引创建失败: {e}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print("=" * 50)
    print("AInsight Pro - KOL Schema 迁移")
    print("=" * 50)

    asyncio.run(migrate_kol_schema())
    asyncio.run(create_indexes())

    print("\n" + "=" * 50)
    print("迁移完成！")
    print("=" * 50)
