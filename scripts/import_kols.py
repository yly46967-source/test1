"""KOL 批量导入工具 - 从 YAML 配置文件导入 KOL 到数据库"""
import asyncio
import sys
import os
from typing import Optional

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from dotenv import load_dotenv
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database.models import (
    Base, KOL, KOLTierEnum, KOLRoleEnum, KOLCategoryEnum
)

load_dotenv()


class KOLImporter:
    """KOL 批量导入器"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self.stats = {
            "total": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0
        }

    async def close(self):
        await self.engine.dispose()

    def _parse_tier(self, tier_str: str) -> KOLTierEnum:
        """解析 tier 字符串为枚举"""
        tier_map = {
            "god": KOLTierEnum.GOD,
            "expert": KOLTierEnum.EXPERT,
            "insider": KOLTierEnum.INSIDER,
            "observer": KOLTierEnum.OBSERVER,
        }
        return tier_map.get(tier_str.lower(), KOLTierEnum.OBSERVER)

    def _parse_role(self, role_str: str) -> KOLRoleEnum:
        """解析 role 字符串为枚举"""
        role_map = {
            "researcher": KOLRoleEnum.RESEARCHER,
            "engineer": KOLRoleEnum.ENGINEER,
            "founder": KOLRoleEnum.FOUNDER,
            "investor": KOLRoleEnum.INVESTOR,
            "journalist": KOLRoleEnum.JOURNALIST,
            "educator": KOLRoleEnum.EDUCATOR,
            "analyst": KOLRoleEnum.ANALYST,
            "influencer": KOLRoleEnum.INFLUENCER,
        }
        return role_map.get(role_str.lower(), KOLRoleEnum.INFLUENCER)

    def _parse_category(self, category_str: str) -> KOLCategoryEnum:
        """解析 category 字符串为枚举"""
        category_map = {
            "llm": KOLCategoryEnum.LLM,
            "cv": KOLCategoryEnum.CV,
            "robotics": KOLCategoryEnum.ROBOTICS,
            "infra": KOLCategoryEnum.INFRA,
            "product": KOLCategoryEnum.PRODUCT,
            "research": KOLCategoryEnum.RESEARCH,
            "startup": KOLCategoryEnum.STARTUP,
            "general": KOLCategoryEnum.GENERAL,
        }
        return category_map.get(category_str.lower(), KOLCategoryEnum.GENERAL)

    def _generate_nitter_url(self, handle: str, nitter_instance: str) -> str:
        """生成 Nitter RSS URL"""
        # 移除 @ 前缀
        handle = handle.lstrip("@")
        return f"{nitter_instance}/{handle}/rss"

    async def import_kol(
        self,
        kol_data: dict,
        nitter_config: dict,
        import_settings: dict
    ) -> str:
        """
        导入单个 KOL

        Returns:
            "created" | "updated" | "skipped" | "error"
        """
        handle = kol_data.get("handle", "").lstrip("@")
        if not handle:
            return "error"

        async with self.async_session() as session:
            try:
                # 检查是否已存在
                result = await session.execute(
                    select(KOL).where(KOL.handle == handle)
                )
                existing = result.scalar_one_or_none()

                if existing and not import_settings.get("overwrite_existing", False):
                    return "skipped"

                # 准备数据
                platform = kol_data.get("platform", "x")
                rss_url = kol_data.get("rss_url")

                # 自动生成 Nitter URL (仅 X/Twitter)
                if not rss_url and platform == "x" and import_settings.get("auto_generate_nitter_url", True):
                    default_instance = import_settings.get(
                        "default_nitter_instance",
                        nitter_config.get("instances", ["https://nitter.privacydev.net"])[0]
                    )
                    rss_url = self._generate_nitter_url(handle, default_instance)

                kol_values = {
                    "handle": handle,
                    "name": kol_data.get("name", handle),
                    "platform": platform,
                    "bio": kol_data.get("bio", ""),
                    "tier": self._parse_tier(kol_data.get("tier", "observer")),
                    "role": self._parse_role(kol_data.get("role", "influencer")),
                    "category": self._parse_category(kol_data.get("category", "general")),
                    "weight": float(kol_data.get("weight", 1.0)),
                    "rss_url": rss_url,
                    "is_active": import_settings.get("enable_on_import", True),
                    "extra_data": {"tags": kol_data.get("tags", [])}
                }

                if existing:
                    # 更新
                    await session.execute(
                        update(KOL).where(KOL.id == existing.id).values(**kol_values)
                    )
                    await session.commit()
                    return "updated"
                else:
                    # 创建
                    kol = KOL(**kol_values)
                    session.add(kol)
                    await session.commit()
                    return "created"

            except Exception as e:
                print(f"    ❌ 导入 {handle} 失败: {e}")
                return "error"

    async def import_from_config(self, config_path: str):
        """从配置文件批量导入 KOL"""
        print(f"正在读取配置文件: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        nitter_config = config.get("nitter", {})
        import_settings = config.get("import_settings", {})

        # 收集所有 KOL
        all_kols = []

        # God Tier
        god_tier = config.get("god_tier", [])
        all_kols.extend(god_tier)
        print(f"  God Tier: {len(god_tier)} 个")

        # Expert Tier
        expert_tier = config.get("expert_tier", [])
        all_kols.extend(expert_tier)
        print(f"  Expert Tier: {len(expert_tier)} 个")

        # Insider Tier
        insider_tier = config.get("insider_tier", [])
        all_kols.extend(insider_tier)
        print(f"  Insider Tier: {len(insider_tier)} 个")

        # Observer Tier
        observer_tier = config.get("observer_tier", [])
        all_kols.extend(observer_tier)
        print(f"  Observer Tier: {len(observer_tier)} 个")

        # Chinese KOLs
        chinese_kols = config.get("chinese_kols", [])
        all_kols.extend(chinese_kols)
        print(f"  中文 KOL: {len(chinese_kols)} 个")

        # GitHub Projects
        github_projects = config.get("github_projects", [])
        all_kols.extend(github_projects)
        print(f"  GitHub 项目: {len(github_projects)} 个")

        print(f"\n总计: {len(all_kols)} 个 KOL")
        print("-" * 50)

        # 批量导入
        for kol_data in all_kols:
            self.stats["total"] += 1
            handle = kol_data.get("handle", "unknown")

            result = await self.import_kol(kol_data, nitter_config, import_settings)

            if result == "created":
                self.stats["created"] += 1
                print(f"  ✅ 创建: {handle}")
            elif result == "updated":
                self.stats["updated"] += 1
                print(f"  🔄 更新: {handle}")
            elif result == "skipped":
                self.stats["skipped"] += 1
                print(f"  ⏭️  跳过: {handle} (已存在)")
            else:
                self.stats["errors"] += 1

        return self.stats


async def main():
    """主函数"""
    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./ainsight.db"
    )

    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "kols.yaml"
    )

    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在: {config_path}")
        return

    print("=" * 50)
    print("AInsight Pro - KOL 批量导入")
    print("=" * 50)
    print(f"数据库: {database_url}")
    print()

    importer = KOLImporter(database_url)

    try:
        stats = await importer.import_from_config(config_path)

        print()
        print("-" * 50)
        print("导入统计:")
        print(f"  总计: {stats['total']}")
        print(f"  创建: {stats['created']}")
        print(f"  更新: {stats['updated']}")
        print(f"  跳过: {stats['skipped']}")
        print(f"  错误: {stats['errors']}")
        print("=" * 50)
        print("✅ 导入完成！")

    finally:
        await importer.close()


async def list_kols():
    """列出数据库中的所有 KOL"""
    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./ainsight.db"
    )

    engine = create_async_engine(database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print("=" * 70)
    print("AInsight Pro - KOL 列表")
    print("=" * 70)

    async with async_session() as session:
        result = await session.execute(
            select(KOL).order_by(KOL.tier, KOL.weight.desc())
        )
        kols = result.scalars().all()

        if not kols:
            print("数据库中没有 KOL")
            return

        current_tier = None
        for kol in kols:
            if kol.tier != current_tier:
                current_tier = kol.tier
                print(f"\n[{current_tier.value.upper()}]")
                print("-" * 60)

            status = "✅" if kol.is_active else "❌"
            rss = "📡" if kol.rss_url else "  "
            print(f"  {status} {rss} @{kol.handle:<20} {kol.name:<20} w={kol.weight:.1f}")

        print()
        print(f"总计: {len(kols)} 个 KOL")

    await engine.dispose()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="KOL 批量导入工具")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有 KOL")
    parser.add_argument("--config", "-c", type=str, help="指定配置文件路径")

    args = parser.parse_args()

    if args.list:
        asyncio.run(list_kols())
    else:
        asyncio.run(main())
