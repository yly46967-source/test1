"""快速导入默认 KOL 名单到数据库"""
import asyncio
import sys
import os

# Windows 编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.database.models import (
    KOL, KOLTierEnum, KOLRoleEnum, KOLCategoryEnum
)

load_dotenv()

# 默认 KOL 名单 (X/Twitter 账号)
DEFAULT_KOLS = [
    "thedorbrothers", "IceBearMiner", "turingou", "NEO_Diver", "Lara82175200",
    "Nikitka_aktikiN", "li12826221", "harrisonitsme", "Trae_ai", "kimrow412",
    "ec12edfae2cb221", "GoSailGlobal", "williamlong", "biggor888", "__oQuery",
    "nash_su", "gkxspace", "mobailabs", "jaredliu_bravo", "unixzii",
    "btcbqr", "guishou_56", "new_voa", "cellinlab", "RobinSeun",
    "satireorcry1", "AnhLanDang66888", "swg209", "jaylenng0788", "Jiaxi_Cui",
    "cb_doge", "11dizhu", "RJDAIGOGO", "bright_hawkins", "RepThomasMassie",
    "jason_chen998", "LeeMmai", "ChandlerGuo", "BrendanEich", "qqqqqf5",
    "luoleiorg", "lilk1kopops", "xiqingongzi", "timbrobro", "h5LPyKL7TP6jjop",
    "JeffBezos", "sun_tian66206", "linwanwan823", "chengeshuo666", "SuTNkwfrFkMhHsG",
    "qi71995219", "himself65", "Freedominc20631", "Stanleysobest", "dlw20202020",
    "milesdeutscher", "aoim33", "shaoxianduipai", "BI3BXI", "Fenng",
    "shydev69", "_kaichen", "openclaw", "steipete", "Maoviews",
    "HAOHONG_CFA", "mranti", "plantegg", "web3annie", "punk2898",
    "robbinfan", "yanhua1010", "ianneo_ai", "snake_w", "435hz",
    "followin_io_zh", "Will_followin", "Pluvio9yte", "Lioneming", "free_lin1921",
    "buaaxhm", "OpenAI", "GeminiApp", "oran_ge", "binghe",
    "xiaojingcanxue", "xbanboo", "lxfater", "op7418", "xiaoheshang2025",
    "xhunt_ai", "lexi_labs", "ginpieck", "imwsl90", "bcjb66",
    "renfanzi", "BTCBruce1", "moltbook", "nikitabier", "0xlianjinshu",
    "qinbafrank", "NoLimitGains", "chenreason", "facai988", "yibingsg",
    "lidangzzz", "maoshen", "onenewbite", "cryptorover", "igeekbb",
    "elonmusk", "PMbackttfuture", "MarioNawfal", "hazuki8964", "Zhangga3",
    "Yelvlv930", "Astronaut_1216", "trondaoCN", "laozhouhengmei", "zuoyeben",
    "sugihara_tatuo", "cz_binance", "JunYin29422166", "lenscn", "CEOBriefing",
    "gengdaJ", "LightCavalryCZ", "Zhan549527", "GGziqiao", "chairbtc",
    "DSM_BTC", "Eddy_Gudong", "cnyzgkc", "happypaidaxing", "AlchainHust",
    "canghe", "nuwa_world", "Crypto_QianXun", "DRbitcoin36", "justinsuntron",
    "LVTGW666", "Kenntnis22", "GFWfrog", "thedankoe", "haowue",
    "goshenggo", "yupi996", "LiYuan6", "BingLiu34173809", "jlxc2001",
    "Khazix0918", "RookieRicardoR", "wi4401649579139", "ji_chunsheng", "AsiaFinance",
    "PartisanReview", "yantanzhang", "IngWeilai", "waveking1314", "AriXZone",
    "firesporp", "blapta", "123olp", "Rumoreconomy", "CryptoSociety42",
    "LIGHTSEEKER1984", "satohou1", "lovelycake", "MZZY8964", "Jaemyung_Lee",
    "tankman2002", "wangzhian8848", "cellier_", "peakji", "Red_Xiao_",
    "hidecloud", "cnpoliwatch", "AsukaOdysseus", "FANSZHANGZHE", "realhoimusk",
    "yhslgg", "nuannuan_share", "FinanceYF5", "OpenBuildxyz", "Michael_Liu93",
    "seclink", "_FORAB", "techeconomyana", "ChinaMacroFacts", "WiseInvest513",
    "Leobai825", "Sea_Bitcoin", "PandaTalk8", "tongbingxue", "kitttchow",
    "xzzzjpl", "MacroMargin", "choicky", "MND_China", "WorldOnWeb3",
    "silverfang88", "catmangox", "wakeup_arrow", "RCL_SPC", "NEBU_KURO",
    "shinjirokoiz", "LawrenceWongST", "KFCQZ", "qiaohuanxin", "ChineseWSJ",
    "ChingteLai", "victorliharcou1", "SpoxCHN_LinJian", "SpoxCHN_MaoNing", "sdcat2",
    "MasuzoeYoichi", "MFA_China", "ChinaMilBugle", "steco_shimizu", "ChnEmbassy_jp",
    "xuejianosaka", "chaofandie"
]

# Nitter 实例
NITTER_INSTANCE = "https://nitter.privacydev.net"


async def import_default_kols():
    """导入默认 KOL 名单"""
    database_url = os.getenv(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./ainsight.db"
    )

    print("=" * 60)
    print("AInsight Pro - 默认 KOL 名单导入")
    print("=" * 60)
    print(f"数据库: {database_url}")
    print(f"待导入: {len(DEFAULT_KOLS)} 个 KOL")
    print("-" * 60)

    engine = create_async_engine(database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    stats = {"created": 0, "skipped": 0, "errors": 0}

    async with async_session() as session:
        for handle in DEFAULT_KOLS:
            handle = handle.lstrip("@")
            try:
                # 检查是否已存在
                result = await session.execute(
                    select(KOL).where(KOL.handle == handle)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    stats["skipped"] += 1
                    print(f"  ⏭️  跳过: @{handle} (已存在)")
                    continue

                # 创建新 KOL
                kol = KOL(
                    handle=handle,
                    name=handle,  # 默认使用 handle 作为名称
                    platform="x",
                    tier=KOLTierEnum.OBSERVER,  # 默认 Observer 等级
                    role=KOLRoleEnum.INFLUENCER,  # 默认 Influencer 角色
                    category=KOLCategoryEnum.GENERAL,  # 默认 General 分类
                    weight=1.0,
                    rss_url=f"{NITTER_INSTANCE}/{handle}/rss",
                    is_active=True,
                    extra_data={"source": "default_list"}
                )
                session.add(kol)
                stats["created"] += 1
                print(f"  ✅ 创建: @{handle}")

            except Exception as e:
                stats["errors"] += 1
                print(f"  ❌ 错误: @{handle} - {e}")

        await session.commit()

    await engine.dispose()

    print("-" * 60)
    print("导入统计:")
    print(f"  总计: {len(DEFAULT_KOLS)}")
    print(f"  创建: {stats['created']}")
    print(f"  跳过: {stats['skipped']}")
    print(f"  错误: {stats['errors']}")
    print("=" * 60)
    print("✅ 导入完成！")


if __name__ == "__main__":
    asyncio.run(import_default_kols())
