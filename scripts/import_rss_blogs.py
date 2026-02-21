"""RSS 博客源批量导入工具 - 从 OPML 文件导入博客 RSS 到 KOL 数据库"""
import asyncio
import sys
import os
import xml.etree.ElementTree as ET
from typing import List, Dict
from urllib.parse import urlparse

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database.models import (
    Base, KOL, KOLTierEnum, KOLRoleEnum, KOLCategoryEnum
)

load_dotenv()


# RSS 博客源列表 (从 OPML 解析)
RSS_BLOGS = [
    {"title": "simonwillison.net", "rss_url": "https://simonwillison.net/atom/everything/", "html_url": "https://simonwillison.net"},
    {"title": "jeffgeerling.com", "rss_url": "https://www.jeffgeerling.com/blog.xml", "html_url": "https://jeffgeerling.com"},
    {"title": "seangoedecke.com", "rss_url": "https://www.seangoedecke.com/rss.xml", "html_url": "https://seangoedecke.com"},
    {"title": "krebsonsecurity.com", "rss_url": "https://krebsonsecurity.com/feed/", "html_url": "https://krebsonsecurity.com"},
    {"title": "daringfireball.net", "rss_url": "https://daringfireball.net/feeds/main", "html_url": "https://daringfireball.net"},
    {"title": "ericmigi.com", "rss_url": "https://ericmigi.com/rss.xml", "html_url": "https://ericmigi.com"},
    {"title": "antirez.com", "rss_url": "http://antirez.com/rss", "html_url": "http://antirez.com"},
    {"title": "idiallo.com", "rss_url": "https://idiallo.com/feed.rss", "html_url": "https://idiallo.com"},
    {"title": "maurycyz.com", "rss_url": "https://maurycyz.com/index.xml", "html_url": "https://maurycyz.com"},
    {"title": "pluralistic.net", "rss_url": "https://pluralistic.net/feed/", "html_url": "https://pluralistic.net"},
    {"title": "shkspr.mobi", "rss_url": "https://shkspr.mobi/blog/feed/", "html_url": "https://shkspr.mobi"},
    {"title": "lcamtuf.substack.com", "rss_url": "https://lcamtuf.substack.com/feed", "html_url": "https://lcamtuf.substack.com"},
    {"title": "mitchellh.com", "rss_url": "https://mitchellh.com/feed.xml", "html_url": "https://mitchellh.com"},
    {"title": "dynomight.net", "rss_url": "https://dynomight.net/feed.xml", "html_url": "https://dynomight.net"},
    {"title": "utcc.utoronto.ca/~cks", "rss_url": "https://utcc.utoronto.ca/~cks/space/blog/?atom", "html_url": "https://utcc.utoronto.ca/~cks"},
    {"title": "xeiaso.net", "rss_url": "https://xeiaso.net/blog.rss", "html_url": "https://xeiaso.net"},
    {"title": "devblogs.microsoft.com/oldnewthing", "rss_url": "https://devblogs.microsoft.com/oldnewthing/feed", "html_url": "https://devblogs.microsoft.com/oldnewthing"},
    {"title": "righto.com", "rss_url": "https://www.righto.com/feeds/posts/default", "html_url": "https://righto.com"},
    {"title": "lucumr.pocoo.org", "rss_url": "https://lucumr.pocoo.org/feed.atom", "html_url": "https://lucumr.pocoo.org"},
    {"title": "skyfall.dev", "rss_url": "https://skyfall.dev/rss.xml", "html_url": "https://skyfall.dev"},
    {"title": "garymarcus.substack.com", "rss_url": "https://garymarcus.substack.com/feed", "html_url": "https://garymarcus.substack.com"},
    {"title": "rachelbythebay.com", "rss_url": "https://rachelbythebay.com/w/atom.xml", "html_url": "https://rachelbythebay.com"},
    {"title": "overreacted.io", "rss_url": "https://overreacted.io/rss.xml", "html_url": "https://overreacted.io"},
    {"title": "timsh.org", "rss_url": "https://timsh.org/rss/", "html_url": "https://timsh.org"},
    {"title": "johndcook.com", "rss_url": "https://www.johndcook.com/blog/feed/", "html_url": "https://johndcook.com"},
    {"title": "gilesthomas.com", "rss_url": "https://gilesthomas.com/feed/rss.xml", "html_url": "https://gilesthomas.com"},
    {"title": "matklad.github.io", "rss_url": "https://matklad.github.io/feed.xml", "html_url": "https://matklad.github.io"},
    {"title": "derekthompson.org", "rss_url": "https://www.theatlantic.com/feed/author/derek-thompson/", "html_url": "https://derekthompson.org"},
    {"title": "evanhahn.com", "rss_url": "https://evanhahn.com/feed.xml", "html_url": "https://evanhahn.com"},
    {"title": "terriblesoftware.org", "rss_url": "https://terriblesoftware.org/feed/", "html_url": "https://terriblesoftware.org"},
    {"title": "rakhim.exotext.com", "rss_url": "https://rakhim.exotext.com/rss.xml", "html_url": "https://rakhim.exotext.com"},
    {"title": "joanwestenberg.com", "rss_url": "https://joanwestenberg.com/rss", "html_url": "https://joanwestenberg.com"},
    {"title": "xania.org", "rss_url": "https://xania.org/feed", "html_url": "https://xania.org"},
    {"title": "micahflee.com", "rss_url": "https://micahflee.com/feed/", "html_url": "https://micahflee.com"},
    {"title": "nesbitt.io", "rss_url": "https://nesbitt.io/feed.xml", "html_url": "https://nesbitt.io"},
    {"title": "construction-physics.com", "rss_url": "https://www.construction-physics.com/feed", "html_url": "https://construction-physics.com"},
    {"title": "tedium.co", "rss_url": "https://feed.tedium.co/", "html_url": "https://tedium.co"},
    {"title": "susam.net", "rss_url": "https://susam.net/feed.xml", "html_url": "https://susam.net"},
    {"title": "entropicthoughts.com", "rss_url": "https://entropicthoughts.com/feed.xml", "html_url": "https://entropicthoughts.com"},
    {"title": "buttondown.com/hillelwayne", "rss_url": "https://buttondown.com/hillelwayne/rss", "html_url": "https://buttondown.com/hillelwayne"},
    {"title": "dwarkesh.com", "rss_url": "https://www.dwarkeshpatel.com/feed", "html_url": "https://dwarkesh.com"},
    {"title": "borretti.me", "rss_url": "https://borretti.me/feed.xml", "html_url": "https://borretti.me"},
    {"title": "wheresyoured.at", "rss_url": "https://www.wheresyoured.at/rss/", "html_url": "https://wheresyoured.at"},
    {"title": "jayd.ml", "rss_url": "https://jayd.ml/feed.xml", "html_url": "https://jayd.ml"},
    {"title": "minimaxir.com", "rss_url": "https://minimaxir.com/index.xml", "html_url": "https://minimaxir.com"},
    {"title": "geohot.github.io", "rss_url": "https://geohot.github.io/blog/feed.xml", "html_url": "https://geohot.github.io"},
    {"title": "paulgraham.com", "rss_url": "http://www.aaronsw.com/2002/feeds/pgessays.rss", "html_url": "https://paulgraham.com"},
    {"title": "filfre.net", "rss_url": "https://www.filfre.net/feed/", "html_url": "https://filfre.net"},
    {"title": "blog.jim-nielsen.com", "rss_url": "https://blog.jim-nielsen.com/feed.xml", "html_url": "https://blog.jim-nielsen.com"},
    {"title": "dfarq.homeip.net", "rss_url": "https://dfarq.homeip.net/feed/", "html_url": "https://dfarq.homeip.net"},
    {"title": "jyn.dev", "rss_url": "https://jyn.dev/atom.xml", "html_url": "https://jyn.dev"},
    {"title": "geoffreylitt.com", "rss_url": "https://www.geoffreylitt.com/feed.xml", "html_url": "https://geoffreylitt.com"},
    {"title": "downtowndougbrown.com", "rss_url": "https://www.downtowndougbrown.com/feed/", "html_url": "https://downtowndougbrown.com"},
    {"title": "brutecat.com", "rss_url": "https://brutecat.com/rss.xml", "html_url": "https://brutecat.com"},
    {"title": "eli.thegreenplace.net", "rss_url": "https://eli.thegreenplace.net/feeds/all.atom.xml", "html_url": "https://eli.thegreenplace.net"},
    {"title": "abortretry.fail", "rss_url": "https://www.abortretry.fail/feed", "html_url": "https://abortretry.fail"},
    {"title": "fabiensanglard.net", "rss_url": "https://fabiensanglard.net/rss.xml", "html_url": "https://fabiensanglard.net"},
    {"title": "oldvcr.blogspot.com", "rss_url": "https://oldvcr.blogspot.com/feeds/posts/default", "html_url": "https://oldvcr.blogspot.com"},
    {"title": "bogdanthegeek.github.io", "rss_url": "https://bogdanthegeek.github.io/blog/index.xml", "html_url": "https://bogdanthegeek.github.io"},
    {"title": "hugotunius.se", "rss_url": "https://hugotunius.se/feed.xml", "html_url": "https://hugotunius.se"},
    {"title": "gwern.net", "rss_url": "https://gwern.substack.com/feed", "html_url": "https://gwern.net"},
    {"title": "berthub.eu", "rss_url": "https://berthub.eu/articles/index.xml", "html_url": "https://berthub.eu"},
    {"title": "chadnauseam.com", "rss_url": "https://chadnauseam.com/rss.xml", "html_url": "https://chadnauseam.com"},
    {"title": "simone.org", "rss_url": "https://simone.org/feed/", "html_url": "https://simone.org"},
    {"title": "it-notes.dragas.net", "rss_url": "https://it-notes.dragas.net/feed/", "html_url": "https://it-notes.dragas.net"},
    {"title": "beej.us", "rss_url": "https://beej.us/blog/rss.xml", "html_url": "https://beej.us"},
    {"title": "hey.paris", "rss_url": "https://hey.paris/index.xml", "html_url": "https://hey.paris"},
    {"title": "danielwirtz.com", "rss_url": "https://danielwirtz.com/rss.xml", "html_url": "https://danielwirtz.com"},
    {"title": "matduggan.com", "rss_url": "https://matduggan.com/rss/", "html_url": "https://matduggan.com"},
    {"title": "refactoringenglish.com", "rss_url": "https://refactoringenglish.com/index.xml", "html_url": "https://refactoringenglish.com"},
    {"title": "worksonmymachine.substack.com", "rss_url": "https://worksonmymachine.substack.com/feed", "html_url": "https://worksonmymachine.substack.com"},
    {"title": "philiplaine.com", "rss_url": "https://philiplaine.com/index.xml", "html_url": "https://philiplaine.com"},
    {"title": "steveblank.com", "rss_url": "https://steveblank.com/feed/", "html_url": "https://steveblank.com"},
    {"title": "bernsteinbear.com", "rss_url": "https://bernsteinbear.com/feed.xml", "html_url": "https://bernsteinbear.com"},
    {"title": "danieldelaney.net", "rss_url": "https://danieldelaney.net/feed", "html_url": "https://danieldelaney.net"},
    {"title": "troyhunt.com", "rss_url": "https://www.troyhunt.com/rss/", "html_url": "https://troyhunt.com"},
    {"title": "herman.bearblog.dev", "rss_url": "https://herman.bearblog.dev/feed/", "html_url": "https://herman.bearblog.dev"},
    {"title": "tomrenner.com", "rss_url": "https://tomrenner.com/index.xml", "html_url": "https://tomrenner.com"},
    {"title": "blog.pixelmelt.dev", "rss_url": "https://blog.pixelmelt.dev/rss/", "html_url": "https://blog.pixelmelt.dev"},
    {"title": "martinalderson.com", "rss_url": "https://martinalderson.com/feed.xml", "html_url": "https://martinalderson.com"},
    {"title": "danielchasehooper.com", "rss_url": "https://danielchasehooper.com/feed.xml", "html_url": "https://danielchasehooper.com"},
    {"title": "chiark.greenend.org.uk/~sgtatham", "rss_url": "https://www.chiark.greenend.org.uk/~sgtatham/quasiblog/feed.xml", "html_url": "https://chiark.greenend.org.uk/~sgtatham"},
    {"title": "grantslatton.com", "rss_url": "https://grantslatton.com/rss.xml", "html_url": "https://grantslatton.com"},
    {"title": "experimental-history.com", "rss_url": "https://www.experimental-history.com/feed", "html_url": "https://experimental-history.com"},
    {"title": "anildash.com", "rss_url": "https://anildash.com/feed.xml", "html_url": "https://anildash.com"},
    {"title": "aresluna.org", "rss_url": "https://aresluna.org/main.rss", "html_url": "https://aresluna.org"},
    {"title": "michael.stapelberg.ch", "rss_url": "https://michael.stapelberg.ch/feed.xml", "html_url": "https://michael.stapelberg.ch"},
    {"title": "miguelgrinberg.com", "rss_url": "https://blog.miguelgrinberg.com/feed", "html_url": "https://miguelgrinberg.com"},
    {"title": "keygen.sh", "rss_url": "https://keygen.sh/blog/feed.xml", "html_url": "https://keygen.sh"},
    {"title": "mjg59.dreamwidth.org", "rss_url": "https://mjg59.dreamwidth.org/data/rss", "html_url": "https://mjg59.dreamwidth.org"},
    {"title": "computer.rip", "rss_url": "https://computer.rip/rss.xml", "html_url": "https://computer.rip"},
    {"title": "tedunangst.com", "rss_url": "https://www.tedunangst.com/flak/rss", "html_url": "https://tedunangst.com"},
]


# 知名博主分类 (用于设置 tier 和 category)
NOTABLE_BLOGS = {
    "simonwillison.net": {"tier": "expert", "category": "llm", "role": "engineer", "name": "Simon Willison"},
    "paulgraham.com": {"tier": "god", "category": "startup", "role": "investor", "name": "Paul Graham"},
    "krebsonsecurity.com": {"tier": "expert", "category": "infra", "role": "journalist", "name": "Brian Krebs"},
    "troyhunt.com": {"tier": "expert", "category": "infra", "role": "educator", "name": "Troy Hunt"},
    "garymarcus.substack.com": {"tier": "expert", "category": "llm", "role": "researcher", "name": "Gary Marcus"},
    "overreacted.io": {"tier": "expert", "category": "product", "role": "engineer", "name": "Dan Abramov"},
    "mitchellh.com": {"tier": "expert", "category": "infra", "role": "founder", "name": "Mitchell Hashimoto"},
    "antirez.com": {"tier": "god", "category": "infra", "role": "engineer", "name": "Salvatore Sanfilippo"},
    "gwern.net": {"tier": "expert", "category": "research", "role": "researcher", "name": "Gwern Branwen"},
    "geohot.github.io": {"tier": "expert", "category": "llm", "role": "founder", "name": "George Hotz"},
    "lucumr.pocoo.org": {"tier": "expert", "category": "infra", "role": "engineer", "name": "Armin Ronacher"},
    "matklad.github.io": {"tier": "expert", "category": "infra", "role": "engineer", "name": "Alex Kladov"},
    "rachelbythebay.com": {"tier": "expert", "category": "infra", "role": "engineer", "name": "Rachel Kroll"},
    "eli.thegreenplace.net": {"tier": "expert", "category": "infra", "role": "engineer", "name": "Eli Bendersky"},
    "steveblank.com": {"tier": "expert", "category": "startup", "role": "educator", "name": "Steve Blank"},
    "dwarkesh.com": {"tier": "insider", "category": "llm", "role": "journalist", "name": "Dwarkesh Patel"},
    "xeiaso.net": {"tier": "insider", "category": "infra", "role": "engineer", "name": "Xe Iaso"},
    "devblogs.microsoft.com/oldnewthing": {"tier": "expert", "category": "infra", "role": "engineer", "name": "Raymond Chen"},
    "fabiensanglard.net": {"tier": "insider", "category": "infra", "role": "engineer", "name": "Fabien Sanglard"},
    "miguelgrinberg.com": {"tier": "insider", "category": "product", "role": "educator", "name": "Miguel Grinberg"},
}


def extract_handle_from_url(html_url: str) -> str:
    """从 URL 提取 handle"""
    parsed = urlparse(html_url)
    # 移除 www. 前缀
    domain = parsed.netloc.replace("www.", "")
    # 处理路径
    path = parsed.path.strip("/")
    if path:
        return f"{domain}/{path}".replace("/", "_")
    return domain


class RSSBlogImporter:
    """RSS 博客源导入器"""

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

    def _get_blog_info(self, title: str) -> Dict:
        """获取博客的分类信息"""
        return NOTABLE_BLOGS.get(title, {
            "tier": "observer",
            "category": "general",
            "role": "influencer",
            "name": title
        })

    def _parse_tier(self, tier_str: str) -> KOLTierEnum:
        tier_map = {
            "god": KOLTierEnum.GOD,
            "expert": KOLTierEnum.EXPERT,
            "insider": KOLTierEnum.INSIDER,
            "observer": KOLTierEnum.OBSERVER,
        }
        return tier_map.get(tier_str.lower(), KOLTierEnum.OBSERVER)

    def _parse_role(self, role_str: str) -> KOLRoleEnum:
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

    async def import_blog(self, blog: Dict) -> str:
        """导入单个博客"""
        title = blog["title"]
        rss_url = blog["rss_url"]
        html_url = blog["html_url"]

        handle = extract_handle_from_url(html_url)
        blog_info = self._get_blog_info(title)

        async with self.async_session() as session:
            try:
                # 检查是否已存在
                result = await session.execute(
                    select(KOL).where(KOL.handle == handle)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    return "skipped"

                # 创建新 KOL
                kol = KOL(
                    handle=handle,
                    name=blog_info.get("name", title),
                    platform="blog",
                    bio=f"Tech blog: {html_url}",
                    tier=self._parse_tier(blog_info.get("tier", "observer")),
                    role=self._parse_role(blog_info.get("role", "influencer")),
                    category=self._parse_category(blog_info.get("category", "general")),
                    weight=1.5 if blog_info.get("tier") in ["god", "expert"] else 1.0,
                    rss_url=rss_url,
                    is_active=True,
                    extra_data={
                        "html_url": html_url,
                        "source_type": "rss_blog",
                        "tags": ["tech", "blog"]
                    }
                )
                session.add(kol)
                await session.commit()
                return "created"

            except Exception as e:
                print(f"    Error importing {title}: {e}")
                return "error"

    async def import_all(self):
        """导入所有博客"""
        print("=" * 60)
        print("AInsight Pro - RSS Blog Import")
        print("=" * 60)
        print(f"Total blogs to import: {len(RSS_BLOGS)}")
        print("-" * 60)

        for blog in RSS_BLOGS:
            self.stats["total"] += 1
            title = blog["title"]

            result = await self.import_blog(blog)

            if result == "created":
                self.stats["created"] += 1
                print(f"  + Created: {title}")
            elif result == "skipped":
                self.stats["skipped"] += 1
                print(f"  - Skipped: {title} (exists)")
            else:
                self.stats["errors"] += 1

        return self.stats


async def main():
    """主函数"""
    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./ainsight.db"
    )

    print(f"Database: {database_url}\n")

    importer = RSSBlogImporter(database_url)

    try:
        stats = await importer.import_all()

        print()
        print("-" * 60)
        print("Import Statistics:")
        print(f"  Total:   {stats['total']}")
        print(f"  Created: {stats['created']}")
        print(f"  Skipped: {stats['skipped']}")
        print(f"  Errors:  {stats['errors']}")
        print("=" * 60)
        print("Done!")

    finally:
        await importer.close()


if __name__ == "__main__":
    asyncio.run(main())
