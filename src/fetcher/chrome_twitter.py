"""
Chrome Profile Twitter 抓取器 - 使用已登录的 Chrome Profile 抓取最新推文

方案：
1. 使用 Playwright 加载已登录 X 的 Chrome Profile
2. 访问用户主页，滚动加载最新推文
3. 提取推文 URL 列表
4. 用 FxTwitter API 获取每条推文的详细数据（互动数据）

使用前提：
- Chrome 浏览器已登录 X 账号
- 运行时 Chrome 需要关闭（避免 Profile 锁定）

依赖：
    pip install playwright
    playwright install chromium
"""
import asyncio
import os
import re
import json
import urllib.request
import urllib.error
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path

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
class TweetData:
    """推文数据"""
    tweet_id: str
    tweet_url: str
    author_handle: str
    author_name: str = ""
    author_avatar: str = ""
    is_verified: bool = False
    text: str = ""
    published_at: Optional[datetime] = None
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    views: int = 0
    bookmarks: int = 0
    media_urls: List[str] = field(default_factory=list)
    is_retweet: bool = False
    is_quote: bool = False
    quote_text: str = ""


@dataclass
class FetchResult:
    """抓取结果"""
    username: str
    tweets: List[TweetData]
    success: bool
    error: Optional[str] = None
    fetch_time: datetime = field(default_factory=datetime.now)


class ChromeTwitterFetcher:
    """使用 Chrome Profile 的 Twitter 抓取器"""

    # Windows 默认 Chrome User Data 路径
    DEFAULT_CHROME_USER_DATA = r"C:\Users\{username}\AppData\Local\Google\Chrome\User Data"

    # FxTwitter API
    FXTWITTER_API = "https://api.fxtwitter.com"

    def __init__(
        self,
        chrome_user_data: Optional[str] = None,
        profile_name: str = "Default",
        headless: bool = False,
        timeout: int = 30000,
        max_tweets: int = 20,
    ):
        """
        初始化抓取器

        Args:
            chrome_user_data: Chrome User Data 目录路径
            profile_name: Profile 名称 (Default, Profile 2, Profile 3 等)
            headless: 是否无头模式
            timeout: 页面加载超时（毫秒）
            max_tweets: 每个用户最大抓取推文数
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("playwright 未安装")

        # 自动检测 Chrome User Data 路径
        if chrome_user_data is None:
            win_user = os.environ.get("USERNAME", "yyl")
            chrome_user_data = self.DEFAULT_CHROME_USER_DATA.format(username=win_user)

        self.chrome_user_data = chrome_user_data
        self.profile_name = profile_name
        self.headless = headless
        self.timeout = timeout
        self.max_tweets = max_tweets

        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._playwright = None

    async def __aenter__(self):
        await self._init_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _init_browser(self):
        """初始化浏览器，尝试多种方式导入 Cookie"""
        self._playwright = await async_playwright().start()

        # 启动独立的浏览器
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        # 创建上下文
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        # 尝试从手动导出的 Cookie 文件加载
        cookie_file = os.path.join(os.path.dirname(__file__), "..", "..", "config", "x_cookies.json")
        if os.path.exists(cookie_file):
            cookies = self._load_cookies_from_file(cookie_file)
            if cookies:
                await self._context.add_cookies(cookies)
                logger.info(f"已从文件导入 {len(cookies)} 个 Cookie")
                return

        # 尝试从 Chrome Profile 导入（可能因 v20 加密失败）
        profile_path = os.path.join(self.chrome_user_data, self.profile_name)
        if os.path.exists(profile_path):
            cookies = self._load_chrome_cookies(profile_path)
            if cookies:
                await self._context.add_cookies(cookies)
                logger.info(f"已从 Chrome 导入 {len(cookies)} 个 Cookie")
                return

        logger.warning("未找到有效 Cookie，将以未登录状态运行")
        logger.warning("提示: 运行 'python -m src.fetcher.chrome_twitter --export-cookies' 导出 Cookie")

    def _load_cookies_from_file(self, cookie_file: str) -> List[dict]:
        """从 JSON 文件加载 Cookie"""
        try:
            with open(cookie_file, "r", encoding="utf-8") as f:
                cookies = json.load(f)

            # 验证格式
            valid_cookies = []
            for c in cookies:
                if "name" in c and "value" in c and "domain" in c:
                    valid_cookies.append({
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c["domain"],
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", True),
                        "httpOnly": c.get("httpOnly", True),
                    })

            return valid_cookies
        except Exception as e:
            logger.error(f"加载 Cookie 文件失败: {e}")
            return []

    def _load_chrome_cookies(self, profile_path: str) -> List[dict]:
        """从 Chrome Profile 加载 X 相关的 Cookie（支持解密）"""
        import sqlite3
        import shutil
        import tempfile
        import base64

        cookie_path = os.path.join(profile_path, "Network", "Cookies")
        if not os.path.exists(cookie_path):
            cookie_path = os.path.join(profile_path, "Cookies")

        if not os.path.exists(cookie_path):
            logger.warning(f"Cookie 文件不存在: {cookie_path}")
            return []

        # 获取解密密钥
        encryption_key = self._get_chrome_encryption_key()

        # 复制 Cookie 文件（避免锁定问题）
        temp_cookie = os.path.join(tempfile.gettempdir(), "chrome_cookies_temp.db")
        try:
            shutil.copy2(cookie_path, temp_cookie)
        except Exception as e:
            logger.error(f"复制 Cookie 文件失败: {e}")
            return []

        cookies = []
        try:
            conn = sqlite3.connect(temp_cookie)
            cursor = conn.cursor()

            # 查询 X/Twitter 相关的 Cookie
            cursor.execute("""
                SELECT host_key, name, value, encrypted_value, path, expires_utc, is_secure, is_httponly, samesite
                FROM cookies
                WHERE host_key LIKE '%twitter.com%' OR host_key LIKE '%x.com%'
            """)

            for row in cursor.fetchall():
                host_key, name, value, encrypted_value, path, expires_utc, is_secure, is_httponly, samesite = row

                # 尝试解密
                decrypted_value = value
                if encrypted_value and encryption_key:
                    try:
                        decrypted_value = self._decrypt_cookie_value(encrypted_value, encryption_key)
                    except Exception as e:
                        logger.debug(f"解密 Cookie {name} 失败: {e}")
                        continue

                if not decrypted_value:
                    continue

                # 转换为 Playwright 格式
                cookie = {
                    "name": name,
                    "value": decrypted_value,
                    "domain": host_key,
                    "path": path or "/",
                    "secure": bool(is_secure),
                    "httpOnly": bool(is_httponly),
                }

                # 设置过期时间
                if expires_utc and expires_utc > 0:
                    # Chrome 使用 Windows epoch (1601-01-01)
                    cookie["expires"] = (expires_utc / 1000000) - 11644473600

                # sameSite
                if samesite == 0:
                    cookie["sameSite"] = "None"
                elif samesite == 1:
                    cookie["sameSite"] = "Lax"
                else:
                    cookie["sameSite"] = "Strict"

                cookies.append(cookie)

            conn.close()
        except Exception as e:
            logger.error(f"读取 Cookie 失败: {e}")
        finally:
            try:
                os.remove(temp_cookie)
            except:
                pass

        return cookies

    def _get_chrome_encryption_key(self) -> Optional[bytes]:
        """获取 Chrome Cookie 加密密钥"""
        try:
            import json
            import base64
            import win32crypt

            local_state_path = os.path.join(self.chrome_user_data, "Local State")
            with open(local_state_path, "r", encoding="utf-8") as f:
                local_state = json.load(f)

            encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
            # 移除 DPAPI 前缀
            encrypted_key = encrypted_key[5:]
            # 使用 Windows DPAPI 解密
            key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
            return key
        except Exception as e:
            logger.warning(f"获取加密密钥失败: {e}")
            return None

    def _decrypt_cookie_value(self, encrypted_value: bytes, key: bytes) -> str:
        """解密 Cookie 值"""
        try:
            from Crypto.Cipher import AES

            # 检查加密版本
            version = encrypted_value[:3]

            if version == b'v20':
                # Chrome v127+ 使用 App-Bound Encryption (v20)
                # v20 格式更复杂，需要通过 Chrome 的 elevation_service 解密
                # 暂时无法直接解密，返回 None
                logger.debug(f"v20 加密格式暂不支持直接解密")
                return ""

            elif version == b'v10':
                # Chrome v80-v126 使用 AES-256-GCM (v10)
                nonce = encrypted_value[3:15]
                ciphertext = encrypted_value[15:-16]
                tag = encrypted_value[-16:]

                cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
                decrypted = cipher.decrypt_and_verify(ciphertext, tag)
                return decrypted.decode('utf-8')

            else:
                # 旧版本使用 DPAPI
                import win32crypt
                return win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1].decode('utf-8')

        except Exception as e:
            raise ValueError(f"解密失败: {e}")

    async def close(self):
        """关闭浏览器"""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("浏览器已关闭")

    async def fetch_user_tweets(self, username: str) -> FetchResult:
        """
        抓取用户最新推文

        Args:
            username: Twitter 用户名（不含 @）

        Returns:
            FetchResult
        """
        username = username.lstrip("@")

        if not self._context:
            await self._init_browser()

        page = await self._context.new_page()
        tweet_urls = []

        try:
            url = f"https://x.com/{username}"
            logger.info(f"访问 @{username} 主页...")

            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)

            # 等待推文加载
            try:
                await page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
            except Exception:
                # 检查是否需要登录
                if await page.query_selector('input[name="text"]'):
                    return FetchResult(
                        username=username,
                        tweets=[],
                        success=False,
                        error="需要登录 - 请确认 Chrome Profile 已登录 X"
                    )
                return FetchResult(
                    username=username,
                    tweets=[],
                    success=False,
                    error="页面加载超时或无推文"
                )

            # 滚动加载更多推文
            await self._scroll_and_collect(page)

            # 提取推文 URL
            tweet_urls = await self._extract_tweet_urls(page, username)
            logger.info(f"@{username}: 找到 {len(tweet_urls)} 条推文 URL")

            # 限制数量
            tweet_urls = tweet_urls[:self.max_tweets]

        except Exception as e:
            logger.error(f"抓取 @{username} 失败: {e}")
            return FetchResult(
                username=username,
                tweets=[],
                success=False,
                error=str(e)
            )
        finally:
            await page.close()

        # 使用 FxTwitter API 获取详细数据
        tweets = []
        for tweet_url in tweet_urls:
            tweet_data = await self._fetch_tweet_details(tweet_url)
            if tweet_data:
                tweets.append(tweet_data)

        logger.info(f"@{username}: 成功获取 {len(tweets)} 条推文详情")

        return FetchResult(
            username=username,
            tweets=tweets,
            success=True
        )

    async def _scroll_and_collect(self, page: Page, scroll_times: int = 5):
        """滚动页面加载更多推文"""
        for i in range(scroll_times):
            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(1.5)

            # 检查是否有新内容加载
            if i % 2 == 0:
                await asyncio.sleep(0.5)

    async def _extract_tweet_urls(self, page: Page, username: str) -> List[str]:
        """从页面提取推文 URL"""
        urls = await page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href*="/status/"]');
                const urls = new Set();

                for (const link of links) {
                    const href = link.href;
                    // 匹配推文 URL 格式
                    if (href.match(/x\\.com\\/\\w+\\/status\\/\\d+$/)) {
                        urls.add(href);
                    }
                }

                return Array.from(urls);
            }
        """)

        # 过滤出该用户的推文（排除转推显示的其他用户推文）
        user_tweets = []
        other_tweets = []

        for url in urls:
            if f"/{username}/status/" in url.lower():
                user_tweets.append(url)
            else:
                other_tweets.append(url)

        # 优先返回用户自己的推文，然后是转推
        return user_tweets + other_tweets

    async def _fetch_tweet_details(self, tweet_url: str) -> Optional[TweetData]:
        """使用 FxTwitter API 获取推文详情"""
        # 从 URL 提取 username 和 tweet_id
        match = re.search(r'x\.com/(\w+)/status/(\d+)', tweet_url)
        if not match:
            return None

        username, tweet_id = match.groups()
        api_url = f"{self.FXTWITTER_API}/{username}/status/{tweet_id}"

        try:
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "AInsight/1.0"}
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            if data.get("code") != 200:
                logger.warning(f"FxTwitter API 错误: {data.get('message')}")
                return None

            tweet = data.get("tweet", {})
            author = tweet.get("author", {})

            # 解析发布时间
            published_at = None
            created_at = tweet.get("created_at", "")
            if created_at:
                try:
                    # FxTwitter 返回格式: "Sun Feb 23 10:30:00 +0000 2025"
                    published_at = datetime.strptime(
                        created_at, "%a %b %d %H:%M:%S %z %Y"
                    )
                except Exception:
                    pass

            # 提取媒体 URL
            media_urls = []
            media = tweet.get("media", {})
            for item in media.get("all", []):
                if item.get("url"):
                    media_urls.append(item["url"])

            # 检查是否是引用推文
            quote = tweet.get("quote")
            quote_text = ""
            if quote:
                qt_author = quote.get("author", {}).get("screen_name", "")
                qt_text = quote.get("text", "")
                quote_text = f"@{qt_author}: {qt_text}"

            return TweetData(
                tweet_id=tweet_id,
                tweet_url=tweet_url,
                author_handle=author.get("screen_name", username),
                author_name=author.get("name", ""),
                author_avatar=author.get("avatar_url", ""),
                is_verified=author.get("verified", False),
                text=tweet.get("text", ""),
                published_at=published_at,
                likes=tweet.get("likes", 0),
                retweets=tweet.get("retweets", 0),
                replies=tweet.get("replies", 0),
                views=tweet.get("views", 0),
                bookmarks=tweet.get("bookmarks", 0),
                media_urls=media_urls,
                is_retweet=False,  # FxTwitter 不直接标记
                is_quote=bool(quote),
                quote_text=quote_text,
            )

        except urllib.error.HTTPError as e:
            logger.warning(f"FxTwitter HTTP 错误 {e.code}: {tweet_url}")
            return None
        except Exception as e:
            logger.warning(f"获取推文详情失败: {e}")
            return None

    async def fetch_multiple_users(
        self,
        usernames: List[str],
        delay_between: float = 3.0,
    ) -> Dict[str, FetchResult]:
        """
        批量抓取多个用户的推文

        Args:
            usernames: 用户名列表
            delay_between: 用户之间的延迟（秒）

        Returns:
            {username: FetchResult} 字典
        """
        results = {}

        for i, username in enumerate(usernames):
            logger.info(f"[{i+1}/{len(usernames)}] 抓取 @{username}")

            result = await self.fetch_user_tweets(username)
            results[username] = result

            # 延迟避免触发风控
            if i < len(usernames) - 1:
                await asyncio.sleep(delay_between)

        # 统计
        success_count = sum(1 for r in results.values() if r.success)
        total_tweets = sum(len(r.tweets) for r in results.values())
        logger.info(f"批量抓取完成: {success_count}/{len(usernames)} 成功, {total_tweets} 条推文")

        return results

    async def fetch_following_list(self, username: str, max_count: int = 500) -> List[dict]:
        """
        获取用户的关注列表

        Args:
            username: Twitter 用户名（不含 @）
            max_count: 最大获取数量

        Returns:
            关注用户列表 [{"handle": "xxx", "name": "xxx", "avatar": "xxx"}, ...]
        """
        username = username.lstrip("@")

        if not self._context:
            await self._init_browser()

        page = await self._context.new_page()
        following = []

        try:
            url = f"https://x.com/{username}/following"
            logger.info(f"访问 @{username} 的关注列表...")

            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)

            # 等待关注列表加载
            try:
                await page.wait_for_selector('[data-testid="UserCell"]', timeout=15000)
            except Exception:
                logger.warning(f"关注列表加载超时")
                return []

            # 滚动加载更多
            last_count = 0
            no_change_count = 0

            while len(following) < max_count and no_change_count < 5:
                # 提取当前页面的用户
                users = await page.evaluate("""
                    () => {
                        const cells = document.querySelectorAll('[data-testid="UserCell"]');
                        const users = [];

                        for (const cell of cells) {
                            try {
                                // 提取用户名
                                const linkEl = cell.querySelector('a[href^="/"]');
                                if (!linkEl) continue;

                                const href = linkEl.getAttribute('href');
                                const handle = href.replace('/', '');

                                // 跳过非用户链接
                                if (handle.includes('/') || handle === '') continue;

                                // 提取显示名称
                                const nameEl = cell.querySelector('[dir="ltr"] span');
                                const name = nameEl ? nameEl.innerText : handle;

                                // 提取头像
                                const avatarEl = cell.querySelector('img[src*="profile_images"]');
                                const avatar = avatarEl ? avatarEl.src : '';

                                users.push({ handle, name, avatar });
                            } catch (e) {
                                console.error('提取用户失败:', e);
                            }
                        }

                        return users;
                    }
                """)

                # 去重并添加
                existing_handles = {u["handle"] for u in following}
                for user in users:
                    if user["handle"] not in existing_handles:
                        following.append(user)
                        existing_handles.add(user["handle"])

                # 检查是否有新数据
                if len(following) == last_count:
                    no_change_count += 1
                else:
                    no_change_count = 0
                    last_count = len(following)

                logger.info(f"已获取 {len(following)} 个关注用户")

                # 滚动加载更多
                await page.evaluate("window.scrollBy(0, 1000)")
                await asyncio.sleep(1.5)

            logger.info(f"关注列表获取完成: {len(following)} 个用户")

        except Exception as e:
            logger.error(f"获取关注列表失败: {e}")
        finally:
            await page.close()

        return following[:max_count]


def get_available_profiles(chrome_user_data: Optional[str] = None) -> List[Dict[str, str]]:
    """获取可用的 Chrome Profile 列表"""
    if chrome_user_data is None:
        win_user = os.environ.get("USERNAME", "yyl")
        chrome_user_data = ChromeTwitterFetcher.DEFAULT_CHROME_USER_DATA.format(username=win_user)

    local_state_path = os.path.join(chrome_user_data, "Local State")

    if not os.path.exists(local_state_path):
        return []

    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        profiles = []
        info_cache = data.get("profile", {}).get("info_cache", {})

        for profile_dir, info in info_cache.items():
            profiles.append({
                "directory": profile_dir,
                "name": info.get("name", ""),
                "gaia_name": info.get("gaia_name", ""),
            })

        return profiles
    except Exception as e:
        logger.error(f"读取 Chrome Profile 失败: {e}")
        return []


async def test_chrome_fetcher():
    """测试 Chrome Profile 抓取器"""
    print("=" * 60)
    print("Chrome Profile Twitter 抓取器测试")
    print("=" * 60)

    # 列出可用 Profile
    print("\n可用的 Chrome Profile:")
    profiles = get_available_profiles()
    for p in profiles:
        print(f"  - {p['directory']}: {p['name']} ({p['gaia_name']})")

    if not profiles:
        print("  未找到 Chrome Profile")
        return

    # 提示用户选择
    print("\n请确保:")
    print("1. Chrome 浏览器已完全关闭")
    print("2. 选择的 Profile 已登录 X")

    # 使用 Default Profile 测试
    profile = "Default"
    print(f"\n使用 Profile: {profile}")

    try:
        async with ChromeTwitterFetcher(
            profile_name=profile,
            headless=False,  # 显示浏览器便于调试
            max_tweets=5,
        ) as fetcher:
            # 测试抓取
            result = await fetcher.fetch_user_tweets("karpathy")

            if result.success:
                print(f"\n✅ 成功抓取 @{result.username}")
                print(f"   推文数: {len(result.tweets)}")

                for tweet in result.tweets[:3]:
                    print(f"\n   📝 {tweet.text[:100]}...")
                    print(f"      ❤️ {tweet.likes}  🔁 {tweet.retweets}  💬 {tweet.replies}")
            else:
                print(f"\n❌ 抓取失败: {result.error}")

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        print("\n可能的原因:")
        print("1. Chrome 浏览器未关闭")
        print("2. Profile 路径不正确")
        print("3. 未安装 playwright")


if __name__ == "__main__":
    asyncio.run(test_chrome_fetcher())
