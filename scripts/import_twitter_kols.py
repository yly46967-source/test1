"""
导入 Twitter KOL 列表

使用方法：
    python scripts/import_twitter_kols.py
    python scripts/import_twitter_kols.py --clear  # 清空现有 KOL 后导入
"""
import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.database import DatabaseService
from src.database.models import KOL, KOLTierEnum, KOLRoleEnum
from src.logger import setup_logging, get_main_logger

# 默认 KOL 列表
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
    "cnpoliwatch", "AsukaOdysseus", "FANSZHANGZHE", "realhoimusk", "yhslgg",
    "nuannuan_share", "FinanceYF5", "OpenBuildxyz", "Michael_Liu93", "seclink",
    "_FORAB", "techeconomyana", "ChinaMacroFacts", "WiseInvest513", "Leobai825",
    "Sea_Bitcoin", "PandaTalk8", "tongbingxue", "kitttchow", "xzzzjpl",
    "MacroMargin", "choicky", "MND_China", "WorldOnWeb3", "silverfang88",
    "catmangox", "wakeup_arrow", "RCL_SPC", "NEBU_KURO", "shinjirokoiz",
    "LawrenceWongST", "KFCQZ", "qiaohuanxin", "ChineseWSJ", "ChingteLai",
    "victorliharcou1", "SpoxCHN_LinJian", "SpoxCHN_MaoNing", "sdcat2", "MasuzoeYoichi",
    "MFA_China", "ChinaMilBugle", "steco_shimizu", "ChnEmbassy_jp", "xuejianosaka",
    "chaofandie", "shydev69", "_kaichen", "openclaw", "steipete",
    "Maoviews", "HAOHONG_CFA", "mranti", "plantegg", "web3annie",
    "punk2898", "robbinfan", "yanhua1010", "ianneo_ai", "snake_w",
    "435hz", "followin_io_zh", "Will_followin", "Pluvio9yte", "Lioneming",
    "free_lin1921", "buaaxhm", "OpenAI", "GeminiApp", "oran_ge",
    "binghe", "xiaojingcanxue", "xbanboo", "lxfater", "op7418",
    "xiaoheshang2025", "xhunt_ai", "lexi_labs", "ginpieck", "imwsl90",
    "bcjb66", "renfanzi", "BTCBruce1", "moltbook", "nikitabier",
    "0xlianjinshu", "qinbafrank", "NoLimitGains", "chenreason", "facai988",
    "yibingsg", "lidangzzz", "maoshen", "onenewbite", "cryptorover",
    "igeekbb", "elonmusk", "PMbackttfuture", "MarioNawfal", "hazuki8964",
    "Zhangga3", "Yelvlv930", "Astronaut_1216", "trondaoCN", "laozhouhengmei",
    "zuoyeben", "sugihara_tatuo", "cz_binance", "JunYin29422166", "lenscn",
    "CEOBriefing", "gengdaJ", "LightCavalryCZ", "Zhan549527", "GGziqiao",
    "chairbtc", "DSM_BTC", "Eddy_Gudong", "cnyzgkc", "happypaidaxing",
    "AlchainHust", "canghe", "nuwa_world", "Crypto_QianXun", "DRbitcoin36",
    "justinsuntron", "LVTGW666", "Kenntnis22", "GFWfrog", "thedankoe",
    "haowue", "goshenggo", "yupi996", "LiYuan6", "BingLiu34173809",
    "jlxc2001", "Khazix0918", "RookieRicardoR", "wi4401649579139", "ji_chunsheng",
    "AsiaFinance", "PartisanReview", "yantanzhang", "IngWeilai", "waveking1314",
    "AriXZone", "firesporp", "blapta", "123olp", "Rumoreconomy",
    "CryptoSociety42", "LIGHTSEEKER1984", "satohou1", "lovelycake", "MZZY8964",
    "Jaemyung_Lee", "tankman2002", "wangzhian8848", "cellier_", "peakji",
    "Red_Xiao_", "hidecloud",
]

# 知名 KOL 设置更高等级
TIER_MAPPING = {
    # GOD 级别 - 行业顶级人物
    "elonmusk": KOLTierEnum.GOD,
    "JeffBezos": KOLTierEnum.GOD,
    "cz_binance": KOLTierEnum.GOD,
    "OpenAI": KOLTierEnum.GOD,
    "GeminiApp": KOLTierEnum.GOD,

    # EXPERT 级别 - 知名从业者
    "BrendanEich": KOLTierEnum.EXPERT,
    "justinsuntron": KOLTierEnum.EXPERT,
    "MarioNawfal": KOLTierEnum.EXPERT,
    "nikitabier": KOLTierEnum.EXPERT,
    "Fenng": KOLTierEnum.EXPERT,
    "mranti": KOLTierEnum.EXPERT,
    "williamlong": KOLTierEnum.EXPERT,

    # INSIDER 级别 - 业内人士
    "op7418": KOLTierEnum.INSIDER,
    "lxfater": KOLTierEnum.INSIDER,
    "lidangzzz": KOLTierEnum.INSIDER,
    "cryptorover": KOLTierEnum.INSIDER,
    "milesdeutscher": KOLTierEnum.INSIDER,
}


async def import_kols(clear_existing: bool = False):
    """导入 KOL 列表"""
    logger = get_main_logger()

    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ainsight.db")
    db = DatabaseService(database_url)
    await db.init_db()

    try:
        async with db.session() as session:
            # 清空现有 KOL
            if clear_existing:
                from sqlalchemy import delete
                result = await session.execute(delete(KOL))
                logger.info(f"已清空 {result.rowcount} 个现有 KOL")

            # 导入新 KOL
            imported = 0
            skipped = 0

            for handle in DEFAULT_KOLS:
                # 检查是否已存在
                from sqlalchemy import select
                existing = await session.execute(
                    select(KOL).where(KOL.handle == handle)
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    continue

                # 确定等级
                tier = TIER_MAPPING.get(handle, KOLTierEnum.OBSERVER)

                # 创建 KOL
                kol = KOL(
                    name=handle,  # 默认使用 handle 作为名称
                    handle=handle,
                    platform="x",
                    tier=tier,
                    role=KOLRoleEnum.INFLUENCER,
                    is_active=True,
                    weight=_get_weight_by_tier(tier),
                )
                session.add(kol)
                imported += 1

            await session.commit()
            logger.info(f"导入完成: {imported} 个新 KOL, {skipped} 个已存在")

    finally:
        await db.close()


def _get_weight_by_tier(tier: KOLTierEnum) -> float:
    """根据等级获取权重"""
    weights = {
        KOLTierEnum.GOD: 3.0,
        KOLTierEnum.EXPERT: 2.0,
        KOLTierEnum.INSIDER: 1.5,
        KOLTierEnum.OBSERVER: 1.0,
    }
    return weights.get(tier, 1.0)


def main():
    parser = argparse.ArgumentParser(description="导入 Twitter KOL 列表")
    parser.add_argument("--clear", action="store_true", help="清空现有 KOL 后导入")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    setup_logging(level=args.log_level)
    asyncio.run(import_kols(clear_existing=args.clear))


if __name__ == "__main__":
    main()
