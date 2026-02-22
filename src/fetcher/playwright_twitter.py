"""
Playwright Twitter 抓取器 - 绕过反爬检测直接抓取 X/Twitter

基于 rebrowser-playwright 的反检测技术：
1. 移除 navigator.webdriver 属性
2. 添加 chrome.runtime 对象
3. 使用真实 Chrome 浏览器

风控策略：
1. 随机延迟（2-5秒）避免请求过快
2. 批次间隔（30秒）避免连续请求
3. 记录上次抓取时间，避免重复抓取
4. 失败重试机制（指数退避）

依赖：
    pip install playwright
    playwright install chromium
"""
import asyncio
import random
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

from src.logger import get_logger

logger = get_logger(__name__)

# 尝试导入 playwright
try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("playwright 未安装，请运行: pip install playwright && playwright install chromium")


@dataclass
class TwitterPost:
    """Twitter 帖子数据"""
    text: str
    author_handle: str
    author_name: str = ""
    author_avatar: str = ""  # 作者头像 URL
    is_verified: bool = False  # 是否认证账号（蓝V）
    post_url: str = ""
    published_at: Optional[datetime] = None
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    views: int = 0
    media_urls: List[str] = field(default_factory=list)
    is_retweet: bool = False
    is_reply: bool = False


@dataclass
class FetchResult:
    """抓取结果"""
    username: str
    tweets: List[TwitterPost]
    success: bool
    error: Optional[str] = None
    fetch_time: datetime = field(default_factory=datetime.now)


# Stealth 脚本 - 移除 webdriver 检测
STEALTH_SCRIPT = """
() => {
    // 移除 webdriver 属性
    delete Object.getPrototypeOf(navigator).webdriver;

    // 添加 chrome.runtime
    if (!window.chrome) {
        window.chrome = {};
    }
    if (!window.chrome.runtime) {
        window.chrome.runtime = {
            PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
            PlatformArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
            PlatformNaclArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
            RequestUpdateCheckStatus: { THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available' },
            OnInstalledReason: { INSTALL: 'install', UPDATE: 'update', CHROME_UPDATE: 'chrome_update', SHARED_MODULE_UPDATE: 'shared_module_update' },
            OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' }
        };
    }

    // 修改 permissions API
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
}
"""


class PlaywrightTwitterFetcher:
    """基于 Playwright 的 Twitter 抓取器（带风控）"""

    # 风控配置
    MIN_DELAY = 2.0          # 最小延迟（秒）
    MAX_DELAY = 5.0          # 最大延迟（秒）
    BATCH_INTERVAL = 30.0    # 批次间隔（秒）
    MAX_RETRIES = 2          # 最大重试次数
    RETRY_DELAY = 10.0       # 重试延迟（秒）

    def __init__(
        self,
        headless: bool = False,  # 默认非无头，避免检测
        timeout: int = 30000,
        max_tweets: int = 20,
        min_delay: float = None,
        max_delay: float = None,
        batch_interval: float = None,
    ):
        """
        初始化抓取器

        Args:
            headless: 是否无头模式（建议 False 以避免检测）
            timeout: 页面加载超时（毫秒）
            max_tweets: 最大抓取推文数
            min_delay: 最小延迟（秒）
            max_delay: 最大延迟（秒）
            batch_interval: 批次间隔（秒）
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("playwright 未安装")

        self.headless = headless
        self.timeout = timeout
        self.max_tweets = max_tweets
        self.min_delay = min_delay or self.MIN_DELAY
        self.max_delay = max_delay or self.MAX_DELAY
        self.batch_interval = batch_interval or self.BATCH_INTERVAL

        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._last_fetch_times: Dict[str, datetime] = {}  # 记录每个用户的上次抓取时间

    async def __aenter__(self):
        await self._init_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _init_browser(self):
        """初始化浏览器"""
        self._playwright = await async_playwright().start()

        # 使用 chromium，添加反检测参数
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--window-size=1280,800',
            ]
        )

        # 创建上下文，模拟真实浏览器
        self._context = await self._browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
        )

        # 注入 stealth 脚本
        await self._context.add_init_script(STEALTH_SCRIPT)

        logger.info("Playwright browser initialized")

    async def close(self):
        """关闭浏览器"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_playwright'):
            await self._playwright.stop()
        logger.info("Playwright browser closed")

    async def _random_delay(self):
        """随机延迟，模拟人类行为"""
        delay = random.uniform(self.min_delay, self.max_delay)
        await asyncio.sleep(delay)

    async def _human_scroll(self, page: Page):
        """模拟人类滚动行为"""
        for _ in range(3):
            # 随机滚动距离
            scroll_distance = random.randint(300, 600)
            await page.evaluate(f'window.scrollBy(0, {scroll_distance})')
            await asyncio.sleep(random.uniform(0.5, 1.5))

    async def fetch_user_tweets(
        self,
        username: str,
        skip_if_recent: bool = True,
        recent_threshold_minutes: int = 30,
    ) -> FetchResult:
        """
        抓取用户的推文

        Args:
            username: Twitter 用户名（不含 @）
            skip_if_recent: 如果最近抓取过则跳过
            recent_threshold_minutes: 最近抓取的阈值（分钟）

        Returns:
            FetchResult
        """
        # 检查是否最近抓取过
        if skip_if_recent and username in self._last_fetch_times:
            last_time = self._last_fetch_times[username]
            if datetime.now() - last_time < timedelta(minutes=recent_threshold_minutes):
                logger.info(f"@{username} recently fetched, skipping")
                return FetchResult(
                    username=username,
                    tweets=[],
                    success=True,
                    error="Skipped: recently fetched"
                )

        if not self._context:
            await self._init_browser()

        page = await self._context.new_page()
        tweets = []

        try:
            url = f"https://x.com/{username}"
            logger.info(f"Fetching @{username}...")

            # 随机延迟
            await self._random_delay()

            # 访问用户主页
            await page.goto(url, wait_until='domcontentloaded', timeout=self.timeout)

            # 等待推文加载
            try:
                await page.wait_for_selector('article', timeout=15000)
            except Exception:
                logger.warning(f"@{username} page load timeout or no tweets")
                return FetchResult(
                    username=username,
                    tweets=[],
                    success=False,
                    error="Page load timeout"
                )

            # 检查是否成功加载
            title = await page.title()
            if '@' not in title and username.lower() not in title.lower():
                logger.warning(f"@{username} page may be redirected or blocked")
                return FetchResult(
                    username=username,
                    tweets=[],
                    success=False,
                    error="Page redirected or blocked"
                )

            # 模拟人类滚动
            await self._human_scroll(page)

            # 提取推文数据
            tweets = await self._extract_tweets(page, username)

            # 记录抓取时间
            self._last_fetch_times[username] = datetime.now()

            logger.info(f"@{username}: {len(tweets)} tweets fetched")

            return FetchResult(
                username=username,
                tweets=tweets,
                success=True
            )

        except Exception as e:
            logger.error(f"Failed to fetch @{username}: {e}")
            return FetchResult(
                username=username,
                tweets=[],
                success=False,
                error=str(e)
            )
        finally:
            await page.close()

    async def _extract_tweets(self, page: Page, username: str) -> List[TwitterPost]:
        """从页面提取推文数据"""
        tweets_data = await page.evaluate("""
            () => {
                const articles = document.querySelectorAll('article');
                const tweets = [];

                for (const article of articles) {
                    try {
                        // 提取文本
                        const textEl = article.querySelector('[data-testid="tweetText"]');
                        const text = textEl ? textEl.innerText : '';

                        // 提取时间
                        const timeEl = article.querySelector('time');
                        const time = timeEl ? timeEl.getAttribute('datetime') : '';

                        // 提取链接
                        const linkEl = article.querySelector('a[href*="/status/"]');
                        const link = linkEl ? linkEl.href : '';

                        // 提取作者
                        const authorEl = article.querySelector('[data-testid="User-Name"]');
                        const authorText = authorEl ? authorEl.innerText : '';
                        const authorMatch = authorText.match(/@(\\w+)/);
                        const authorHandle = authorMatch ? authorMatch[1] : '';
                        const authorName = authorText.split('\\n')[0] || '';

                        // 提取头像
                        const avatarEl = article.querySelector('[data-testid="Tweet-User-Avatar"] img');
                        const authorAvatar = avatarEl ? avatarEl.src : '';

                        // 检查是否认证（蓝V）- 查找认证图标
                        const verifiedEl = article.querySelector('[data-testid="User-Name"] svg[aria-label*="Verified"], [data-testid="User-Name"] svg[data-testid="icon-verified"]');
                        const isVerified = !!verifiedEl;

                        // 提取互动数据
                        const getMetric = (testId) => {
                            const el = article.querySelector(`[data-testid="${testId}"]`);
                            if (!el) return 0;
                            const text = el.innerText || el.getAttribute('aria-label') || '';
                            const match = text.match(/([\\d,]+)/);
                            return match ? parseInt(match[1].replace(/,/g, '')) : 0;
                        };

                        const replies = getMetric('reply');
                        const retweets = getMetric('retweet');
                        const likes = getMetric('like');

                        // 提取媒体
                        const mediaEls = article.querySelectorAll('img[src*="pbs.twimg.com/media"]');
                        const mediaUrls = Array.from(mediaEls).map(img => img.src);

                        // 检查是否是转推
                        const isRetweet = article.innerText.includes('Reposted') ||
                                         article.innerText.includes('Retweeted');

                        // 检查是否是回复
                        const isReply = article.innerText.includes('Replying to');

                        if (text || link) {
                            tweets.push({
                                text,
                                time,
                                link,
                                authorHandle,
                                authorName,
                                authorAvatar,
                                isVerified,
                                replies,
                                retweets,
                                likes,
                                mediaUrls,
                                isRetweet,
                                isReply
                            });
                        }
                    } catch (e) {
                        console.error('Failed to extract tweet:', e);
                    }
                }

                return tweets;
            }
        """)

        # 转换为 TwitterPost 对象
        tweets = []
        for data in tweets_data[:self.max_tweets]:
            try:
                published_at = None
                if data.get('time'):
                    try:
                        published_at = datetime.fromisoformat(data['time'].replace('Z', '+00:00'))
                    except Exception:
                        pass

                tweet = TwitterPost(
                    text=data.get('text', ''),
                    author_handle=data.get('authorHandle', username),
                    author_name=data.get('authorName', ''),
                    author_avatar=data.get('authorAvatar', ''),
                    is_verified=data.get('isVerified', False),
                    post_url=data.get('link', ''),
                    published_at=published_at,
                    likes=data.get('likes', 0),
                    retweets=data.get('retweets', 0),
                    replies=data.get('replies', 0),
                    media_urls=data.get('mediaUrls', []),
                    is_retweet=data.get('isRetweet', False),
                    is_reply=data.get('isReply', False),
                )
                tweets.append(tweet)
            except Exception as e:
                logger.warning(f"Failed to parse tweet: {e}")

        return tweets

    async def fetch_multiple_users(
        self,
        usernames: List[str],
        batch_size: int = 5,
        skip_if_recent: bool = True,
    ) -> Dict[str, FetchResult]:
        """
        批量抓取多个用户的推文（带风控）

        Args:
            usernames: 用户名列表
            batch_size: 每批处理数量
            skip_if_recent: 如果最近抓取过则跳过

        Returns:
            {username: FetchResult} 字典
        """
        results = {}
        total = len(usernames)

        # 分批处理
        for i in range(0, total, batch_size):
            batch = usernames[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total + batch_size - 1) // batch_size

            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} users)")

            # 顺序处理每个用户（避免并发触发风控）
            for username in batch:
                result = await self.fetch_user_tweets(
                    username,
                    skip_if_recent=skip_if_recent
                )
                results[username] = result

                # 如果失败，增加延迟
                if not result.success:
                    await asyncio.sleep(self.RETRY_DELAY)

            # 批次间隔
            if i + batch_size < total:
                logger.info(f"Batch interval: {self.batch_interval}s")
                await asyncio.sleep(self.batch_interval)

        # 统计结果
        success_count = sum(1 for r in results.values() if r.success)
        total_tweets = sum(len(r.tweets) for r in results.values())
        logger.info(f"Fetch completed: {success_count}/{total} users, {total_tweets} tweets")

        return results


async def fetch_twitter_with_playwright(
    usernames: List[str],
    max_tweets: int = 20,
    headless: bool = False,
    batch_size: int = 5,
) -> Dict[str, List[TwitterPost]]:
    """
    便捷函数：使用 Playwright 抓取 Twitter

    Args:
        usernames: 用户名列表
        max_tweets: 每个用户最大推文数
        headless: 是否无头模式
        batch_size: 每批处理数量

    Returns:
        {username: [tweets]} 字典
    """
    async with PlaywrightTwitterFetcher(
        headless=headless,
        max_tweets=max_tweets
    ) as fetcher:
        results = await fetcher.fetch_multiple_users(usernames, batch_size=batch_size)
        return {k: v.tweets for k, v in results.items()}


# 转换为 RawContentItem 格式
def convert_to_raw_content(
    tweets: List[TwitterPost],
    kol_id: Optional[int] = None,
    kol_tier: str = "observer"
) -> List[Dict[str, Any]]:
    """
    将 TwitterPost 转换为 RawContentItem 格式

    Args:
        tweets: 推文列表
        kol_id: KOL 数据库 ID
        kol_tier: KOL 等级

    Returns:
        RawContentItem 格式的字典列表
    """
    items = []
    for tweet in tweets:
        item = {
            "text": tweet.text,
            "source_type": "x_post",
            "source_url": tweet.post_url,
            "title": None,
            "published_at": tweet.published_at,
            "kol_id": kol_id,
            "kol_name": tweet.author_name,
            "kol_handle": tweet.author_handle,
            "kol_tier": kol_tier,
            "metrics": {
                "likes": tweet.likes,
                "retweets": tweet.retweets,
                "replies": tweet.replies,
                "views": tweet.views,
            },
            "media_urls": tweet.media_urls,
            "raw_data": {
                "is_retweet": tweet.is_retweet,
                "is_reply": tweet.is_reply,
            },
        }
        items.append(item)
    return items


def filter_today_tweets(tweets: List[TwitterPost]) -> List[TwitterPost]:
    """过滤出今日的推文"""
    today = datetime.now().date()
    return [t for t in tweets if t.published_at and t.published_at.date() == today]
