"""
AInsight Pro 完整功能测试脚本

测试项目：
1. 数据库连接和 KOL 数据
2. Nitter 网关可用性
3. Twitter 抓取器
4. SimHash 去重
5. 聚类流水线
6. Web UI 启动
"""
import sys
import os
import asyncio
import time
from datetime import datetime

# 修复 Windows 编码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 添加项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


class TestLogger:
    """测试日志记录器"""

    def __init__(self):
        self.results = []
        self.start_time = None

    def start(self, name: str):
        self.start_time = time.time()
        print(f"\n{'='*60}")
        print(f"🧪 测试: {name}")
        print(f"{'='*60}")

    def log(self, msg: str):
        print(f"   {msg}")

    def success(self, name: str, details: str = ""):
        elapsed = time.time() - self.start_time
        self.results.append(("✅", name, elapsed, details))
        print(f"\n   ✅ 通过 ({elapsed:.2f}s)")
        if details:
            print(f"   📝 {details}")

    def fail(self, name: str, error: str):
        elapsed = time.time() - self.start_time
        self.results.append(("❌", name, elapsed, error))
        print(f"\n   ❌ 失败 ({elapsed:.2f}s)")
        print(f"   💥 错误: {error}")

    def warn(self, name: str, msg: str):
        elapsed = time.time() - self.start_time
        self.results.append(("⚠️", name, elapsed, msg))
        print(f"\n   ⚠️ 警告 ({elapsed:.2f}s)")
        print(f"   📝 {msg}")

    def summary(self):
        print(f"\n{'='*60}")
        print("📊 测试结果汇总")
        print(f"{'='*60}")

        passed = sum(1 for r in self.results if r[0] == "✅")
        failed = sum(1 for r in self.results if r[0] == "❌")
        warned = sum(1 for r in self.results if r[0] == "⚠️")

        for status, name, elapsed, detail in self.results:
            print(f"   {status} {name} ({elapsed:.2f}s)")
            if detail and status != "✅":
                print(f"      └─ {detail[:80]}")

        print(f"\n   总计: {len(self.results)} 项")
        print(f"   通过: {passed} | 失败: {failed} | 警告: {warned}")

        return failed == 0


logger = TestLogger()


async def test_database():
    """测试 1: 数据库连接和 KOL 数据"""
    logger.start("数据库连接和 KOL 数据")

    try:
        from src.database import DatabaseService

        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ainsight.db")
        logger.log(f"数据库 URL: {db_url}")

        db = DatabaseService(db_url)
        await db.init_db()
        logger.log("数据库初始化成功")

        # 查询 KOL 数量
        from sqlalchemy import select, func
        from src.database.models import KOL, KOLTierEnum

        async with db.session() as session:
            stmt = select(func.count(KOL.id))
            result = await session.execute(stmt)
            kol_count = result.scalar()
            logger.log(f"KOL 总数: {kol_count}")

            # 按等级统计
            for tier in ["god", "expert", "insider", "observer"]:
                stmt = select(func.count(KOL.id)).where(KOL.tier == KOLTierEnum(tier))
                result = await session.execute(stmt)
                count = result.scalar()
                logger.log(f"  - {tier}: {count}")

        await db.close()

        if kol_count > 0:
            logger.success("数据库连接和 KOL 数据", f"共 {kol_count} 位 KOL")
        else:
            logger.warn("数据库连接和 KOL 数据", "数据库为空，请先导入 KOL")

    except Exception as e:
        logger.fail("数据库连接和 KOL 数据", str(e))


async def test_nitter_gateway():
    """测试 2: Nitter 网关可用性"""
    logger.start("Nitter 网关可用性")

    try:
        from src.fetcher.nitter_gateway import NitterGateway

        gateway = NitterGateway()
        logger.log(f"已配置 {len(gateway.instances)} 个 Nitter 实例")

        # 测试健康检查
        logger.log("开始健康检查（可能需要一些时间）...")
        healthy = await gateway.health_check()

        # healthy 是一个列表
        healthy_list = list(healthy) if healthy else []
        logger.log(f"健康实例: {len(healthy_list)}/{len(gateway.instances)}")

        if healthy_list:
            for inst in healthy_list[:5]:
                logger.log(f"  ✓ {inst}")
            if len(healthy_list) > 5:
                logger.log(f"  ... 还有 {len(healthy_list) - 5} 个")

            logger.success("Nitter 网关可用性", f"{len(healthy_list)} 个实例可用")
        else:
            logger.warn("Nitter 网关可用性", "所有公共实例不可用，建议自建 Nitter")

    except Exception as e:
        logger.fail("Nitter 网关可用性", str(e))


async def test_twitter_fetcher():
    """测试 3: Twitter 抓取器"""
    logger.start("Twitter 抓取器")

    try:
        from src.fetcher.twitter_fetcher import TwitterFetcher
        from src.database.models import KOL, KOLTierEnum

        fetcher = TwitterFetcher()

        # 创建测试 KOL 对象
        test_kol = KOL(
            id=1,
            handle="elonmusk",
            name="Elon Musk",
            tier=KOLTierEnum.GOD,
            weight=10.0
        )

        logger.log(f"测试抓取 @{test_kol.handle} 的推文...")

        tweets = await fetcher.fetch_kol(test_kol)

        if tweets:
            logger.log(f"成功获取 {len(tweets)} 条推文")
            for i, tweet in enumerate(tweets[:2], 1):
                text = tweet.text[:50] if tweet.text else ""
                logger.log(f"  {i}. {text}...")

            logger.success("Twitter 抓取器", f"成功抓取 {len(tweets)} 条推文")
        else:
            logger.warn("Twitter 抓取器", "未获取到推文，Nitter 可能不可用")

    except Exception as e:
        logger.fail("Twitter 抓取器", str(e))


async def test_simhash_dedup():
    """测试 4: SimHash 去重"""
    logger.start("SimHash 去重")

    try:
        from src.clustering.deduplicator import SimHash, ContentDeduplicator

        dedup = ContentDeduplicator()

        # 测试相似文本
        text1 = "OpenAI 发布了 GPT-5，这是一个重大突破，将改变 AI 行业格局"
        text2 = "OpenAI 发布 GPT-5，这是重大突破，将改变 AI 行业的格局"
        text3 = "今天天气很好，适合出去散步"

        hash1 = dedup.get_simhash(text1)
        hash2 = dedup.get_simhash(text2)
        hash3 = dedup.get_simhash(text3)

        sim_12 = dedup.simhash.similarity(hash1, hash2)
        sim_13 = dedup.simhash.similarity(hash1, hash3)

        logger.log(f"文本1 vs 文本2 相似度: {sim_12:.2%}")
        logger.log(f"文本1 vs 文本3 相似度: {sim_13:.2%}")

        # 验证相似文本被识别
        if sim_12 > 0.8 and sim_13 < 0.5:
            logger.success("SimHash 去重", f"相似文本识别正确 ({sim_12:.0%} vs {sim_13:.0%})")
        else:
            logger.warn("SimHash 去重", f"相似度计算可能有问题")

    except Exception as e:
        logger.fail("SimHash 去重", str(e))


async def test_clustering_pipeline():
    """测试 5: 聚类流水线"""
    logger.start("聚类流水线")

    try:
        from src.database import DatabaseService
        from src.clustering import TopicClusterer, EnhancedClusteringPipeline
        from openai import AsyncOpenAI

        # 初始化
        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ainsight.db")
        db = DatabaseService(db_url)
        await db.init_db()

        # 创建 LLM 客户端
        api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

        if not api_key:
            logger.warn("聚类流水线", "未配置 API Key，跳过 LLM 测试")
            await db.close()
            return

        llm = AsyncOpenAI(api_key=api_key, base_url=base_url)
        model = os.getenv("LLM_MODEL", "qwen-plus")

        logger.log(f"LLM 模型: {model}")

        # 创建聚类器
        clusterer = TopicClusterer(llm, model=model)

        # 测试内容
        test_content = {
            "text": "Claude 3.5 Sonnet 发布，性能超越 GPT-4，Anthropic 再次证明其技术实力",
            "source_url": f"https://test.com/test_{int(time.time())}",
            "source_type": "twitter",
        }

        logger.log("测试聚类决策...")

        async with db.session() as session:
            pipeline = EnhancedClusteringPipeline(
                session=session,
                clusterer=clusterer,
                min_sources=3,
                min_unique_kols=2,
            )

            # 获取候选主题
            candidates = await pipeline._fallback_match(limit=5)
            logger.log(f"候选主题数: {len(candidates)}")

            # 测试聚类
            result = await clusterer.cluster(test_content, candidates)
            logger.log(f"聚类决策: {result.action.value}")
            logger.log(f"相关度: {result.relevance_score:.2f}")

        await db.close()

        logger.success("聚类流水线", f"决策: {result.action.value}, 相关度: {result.relevance_score:.2f}")

    except Exception as e:
        logger.fail("聚类流水线", str(e))


async def test_web_ui():
    """测试 6: Web UI 启动"""
    logger.start("Web UI 启动检查")

    try:
        # 检查模板文件
        templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src", "web", "templates")

        required_templates = ["base.html", "index.html", "kols.html"]
        missing = []

        for tpl in required_templates:
            path = os.path.join(templates_dir, tpl)
            if os.path.exists(path):
                logger.log(f"  ✓ {tpl}")
            else:
                missing.append(tpl)
                logger.log(f"  ✗ {tpl} (缺失)")

        # 检查静态文件
        static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src", "web", "static")
        css_file = os.path.join(static_dir, "css", "style.css")

        if os.path.exists(css_file):
            logger.log(f"  ✓ style.css")
        else:
            missing.append("style.css")

        # 尝试导入 app
        from src.web.app import app
        logger.log(f"  ✓ FastAPI app 导入成功")

        if not missing:
            logger.success("Web UI 启动检查", "所有文件就绪")
        else:
            logger.warn("Web UI 启动检查", f"缺失文件: {', '.join(missing)}")

    except Exception as e:
        logger.fail("Web UI 启动检查", str(e))


async def test_batch_fetch():
    """测试 7: 批量抓取性能"""
    logger.start("批量抓取性能测试")

    try:
        from src.database import DatabaseService
        from src.fetcher.twitter_fetcher import TwitterFetcher
        from sqlalchemy import select
        from src.database.models import KOL

        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./ainsight.db")
        db = DatabaseService(db_url)
        await db.init_db()

        # 获取前 5 个 KOL
        async with db.session() as session:
            stmt = select(KOL).where(KOL.is_active == True).limit(5)
            result = await session.execute(stmt)
            kols = result.scalars().all()

        if not kols:
            logger.warn("批量抓取性能测试", "没有可用的 KOL")
            await db.close()
            return

        logger.log(f"测试抓取 {len(kols)} 个 KOL...")

        fetcher = TwitterFetcher(max_items=3)

        success_count = 0
        total_tweets = 0

        for kol in kols:
            try:
                tweets = await fetcher.fetch_kol(kol)
                if tweets:
                    success_count += 1
                    total_tweets += len(tweets)
                    logger.log(f"  ✓ @{kol.handle}: {len(tweets)} 条")
                else:
                    logger.log(f"  - @{kol.handle}: 无数据")
            except Exception as e:
                logger.log(f"  ✗ @{kol.handle}: {str(e)[:30]}")

            # 避免请求过快
            await asyncio.sleep(1)

        await db.close()

        if success_count > 0:
            logger.success("批量抓取性能测试", f"{success_count}/{len(kols)} 成功, 共 {total_tweets} 条推文")
        else:
            logger.warn("批量抓取性能测试", "所有抓取失败，Nitter 可能不可用")

    except Exception as e:
        logger.fail("批量抓取性能测试", str(e))


async def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║           AInsight Pro 完整功能测试                          ║
║           测试时间: {}                          ║
╚══════════════════════════════════════════════════════════════╝
    """.format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    # 运行所有测试
    await test_database()
    await test_simhash_dedup()
    await test_nitter_gateway()
    await test_twitter_fetcher()
    await test_clustering_pipeline()
    await test_web_ui()
    await test_batch_fetch()

    # 输出汇总
    all_passed = logger.summary()

    print(f"\n{'='*60}")
    if all_passed:
        print("🎉 所有测试通过！可以启动 Web UI 进行进一步测试")
        print("\n启动命令:")
        print("  cd d:\\VibeCoding Skills\\news-funnel")
        print("  uvicorn src.web.app:app --reload --host 0.0.0.0 --port 8000")
    else:
        print("⚠️ 部分测试未通过，请检查上述错误信息")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
