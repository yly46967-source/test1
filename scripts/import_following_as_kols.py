"""
从 X 关注列表导入 KOL

使用方法：
    python scripts/import_following_as_kols.py [--username YOUR_USERNAME]

如果不指定 username，会尝试从 Cookie 中获取当前登录用户
"""
import asyncio
import argparse
import sys
import os

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.fetcher.chrome_twitter import ChromeTwitterFetcher
from src.database import DatabaseService
from src.database.models import KOL
from sqlalchemy import select, delete


async def get_current_username(fetcher: ChromeTwitterFetcher) -> str:
    """从 X 获取当前登录用户名"""
    page = await fetcher._context.new_page()
    try:
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # 尝试从页面获取用户名
        username = await page.evaluate("""
            () => {
                // 从侧边栏获取用户名
                const profileLink = document.querySelector('a[data-testid="AppTabBar_Profile_Link"]');
                if (profileLink) {
                    const href = profileLink.getAttribute('href');
                    return href ? href.replace('/', '') : null;
                }
                return null;
            }
        """)

        return username
    finally:
        await page.close()


async def import_following_as_kols(username: str = None, max_count: int = 500):
    """从关注列表导入 KOL"""
    print("=" * 60)
    print("从 X 关注列表导入 KOL")
    print("=" * 60)

    # 初始化数据库
    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ainsight_v3.db")
    db = DatabaseService(database_url)
    await db.init_db()

    try:
        async with ChromeTwitterFetcher(
            profile_name="Default",
            headless=False,
            max_tweets=10,
        ) as fetcher:
            # 如果没有指定用户名，尝试获取当前登录用户
            if not username:
                print("\n正在获取当前登录用户...")
                username = await get_current_username(fetcher)
                if not username:
                    print("[ERROR] 无法获取当前登录用户，请使用 --username 参数指定")
                    return

            print(f"\n当前用户: @{username}")
            print(f"正在获取关注列表 (最多 {max_count} 个)...")

            # 获取关注列表
            following = await fetcher.fetch_following_list(username, max_count=max_count)

            if not following:
                print("[ERROR] 未获取到关注列表")
                return

            print(f"\n获取到 {len(following)} 个关注用户")

            # 删除现有 KOL
            async with db.async_session() as session:
                # 先统计现有数量
                result = await session.execute(select(KOL))
                existing_kols = result.scalars().all()
                print(f"\n删除现有 {len(existing_kols)} 个 KOL...")

                await session.execute(delete(KOL))
                await session.commit()

            # 导入新 KOL
            async with db.async_session() as session:
                created = 0
                for user in following:
                    handle = user["handle"]
                    name = user.get("name", handle)

                    kol = KOL(
                        handle=handle,
                        name=name,
                        platform="x",
                        is_active=True,
                    )
                    session.add(kol)
                    created += 1

                await session.commit()

            print(f"\n[OK] 成功导入 {created} 个 KOL")
            print("\n前 10 个 KOL:")
            for user in following[:10]:
                print(f"  @{user['handle']}: {user.get('name', '')}")

    finally:
        await db.close()


def main():
    parser = argparse.ArgumentParser(description="从 X 关注列表导入 KOL")
    parser.add_argument("--username", type=str, help="X 用户名（不含 @）")
    parser.add_argument("--max", type=int, default=500, help="最大导入数量")
    args = parser.parse_args()

    asyncio.run(import_following_as_kols(username=args.username, max_count=args.max))


if __name__ == "__main__":
    main()
