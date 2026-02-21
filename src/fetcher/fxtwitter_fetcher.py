"""FxTwitter API 抓取器 - 替代 Nitter 的稳定方案

基于 x-fetcher 项目的 fxtwitter API 实现，支持：
- 普通推文抓取
- X Article 长文章完整 Markdown 提取
- syndication API 备用方案
"""
import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import httpx

from src.logger import get_logger
from src.database.models import KOL
from .ainsight_fetcher import RawContentItem

logger = get_logger(__name__)


@dataclass
class FxTweetContent:
    """FxTwitter 推文内容"""
    text: str
    tweet_url: str
    tweet_id: str
    author_handle: str
    author_name: Optional[str] = None
    published_at: Optional[datetime] = None

    # KOL 信息
    kol_id: Optional[int] = None
    kol_tier: Optional[str] = None
    kol_weight: float = 1.0

    # 互动数据
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    views: int = 0
    bookmarks: int = 0

    # 媒体
    media_urls: List[str] = field(default_factory=list)

    # X Article 长文章
    is_article: bool = False
    article_title: Optional[str] = None
    article_content: Optional[str] = None  # Markdown 格式
    article_cover: Optional[str] = None

    # 元数据
    is_retweet: bool = False
    is_reply: bool = False
    reply_to: Optional[str] = None
    source_api: str = "fxtwitter"  # fxtwitter 或 syndication


class FxTwitterFetcher:
    """基于 fxtwitter API 的推文抓取器"""

    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    TIMEOUT = 15

    def __init__(self, max_items: int = 20):
        self.max_items = max_items

    # ==================== 核心 API 方法 ====================

    async def fetch_tweet_by_url(self, url: str) -> Optional[FxTweetContent]:
        """
        通过 URL 抓取单条推文

        优先使用 fxtwitter API，失败后尝试 syndication API
        """
        tweet_id = self._extract_tweet_id(url)
        username = self._extract_username(url)

        if not tweet_id:
            logger.warning(f"[FxTwitter] 无法从 URL 提取 tweet_id: {url}")
            return None

        # 方法1: fxtwitter API
        content = await self._fetch_via_fxtwitter(url)
        if content:
            return content

        # 方法2: syndication API (备用)
        content = await self._fetch_via_syndication(tweet_id, username)
        if content:
            return content

        logger.warning(f"[FxTwitter] 所有方法均失败: {url}")
        return None

    async def fetch_user_tweets(
        self,
        username: str,
        kol: Optional[KOL] = None,
    ) -> List[FxTweetContent]:
        """
        抓取用户最近推文

        注意: fxtwitter 不直接支持时间线 API，
        这里通过 RSS 或其他方式获取推文 URL 列表后逐条抓取
        """
        # fxtwitter 支持 RSS: https://api.fxtwitter.com/{username}/rss
        # 但实际上这个 RSS 功能不稳定，建议配合其他来源获取 URL 列表

        # 暂时返回空，后续可以集成 RSS 解析
        logger.info(f"[FxTwitter] fetch_user_tweets 暂未实现完整时间线抓取")
        return []

    async def fetch_kol(self, kol: KOL) -> List[FxTweetContent]:
        """
        抓取单个 KOL 的推文

        兼容 TwitterFetcher 接口
        """
        return await self.fetch_user_tweets(kol.handle.lstrip("@"), kol)

    async def fetch_kols_batch(
        self,
        kols: List[KOL],
        concurrency: int = 10,
    ) -> Tuple[List[FxTweetContent], Dict[str, int]]:
        """
        批量抓取多个 KOL

        Args:
            kols: KOL 列表
            concurrency: 并发数 (默认 10，参考 ai-daily-digest)

        Returns:
            (所有内容, 统计信息)
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch_with_semaphore(kol: KOL):
            async with semaphore:
                return kol.handle, await self.fetch_kol(kol)

        tasks = [fetch_with_semaphore(kol) for kol in kols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items = []
        stats = {"success": 0, "failed": 0, "total_items": 0}

        for result in results:
            if isinstance(result, Exception):
                stats["failed"] += 1
                logger.error(f"[FxTwitter] 抓取异常: {result}")
            else:
                handle, items = result
                if items:
                    all_items.extend(items)
                    stats["success"] += 1
                    stats["total_items"] += len(items)
                else:
                    stats["failed"] += 1

        return all_items, stats

    async def fetch_tweets_by_urls(
        self,
        urls: List[str],
        concurrency: int = 10,
    ) -> List[FxTweetContent]:
        """
        批量抓取多个推文 URL

        这是最实用的方法：配合其他来源获取 URL 列表后批量抓取
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch_with_semaphore(url: str):
            async with semaphore:
                return await self.fetch_tweet_by_url(url)

        tasks = [fetch_with_semaphore(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        items = []
        for result in results:
            if isinstance(result, FxTweetContent):
                items.append(result)
            elif isinstance(result, Exception):
                logger.warning(f"[FxTwitter] 抓取失败: {result}")

        return items

    # ==================== fxtwitter API ====================

    async def _fetch_via_fxtwitter(self, url: str) -> Optional[FxTweetContent]:
        """通过 fxtwitter API 获取推文"""
        # 将 x.com 或 twitter.com 替换为 api.fxtwitter.com
        api_url = re.sub(r'(x\.com|twitter\.com)', 'api.fxtwitter.com', url)

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                resp = await client.get(
                    api_url,
                    headers={"User-Agent": self.USER_AGENT},
                    follow_redirects=True,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    return self._parse_fxtwitter_response(data, url)
                else:
                    logger.warning(f"[FxTwitter] API 返回 {resp.status_code}: {url}")

        except Exception as e:
            logger.warning(f"[FxTwitter] API 错误: {e}")

        return None

    def _parse_fxtwitter_response(
        self,
        data: Dict[str, Any],
        original_url: str,
    ) -> Optional[FxTweetContent]:
        """解析 fxtwitter API 响应"""
        tweet = data.get("tweet", {})
        if not tweet:
            return None

        author = tweet.get("author", {})
        article = tweet.get("article")

        # 解析发布时间
        published_at = None
        created_str = tweet.get("created_at") or (article.get("created_at") if article else None)
        if created_str:
            try:
                # fxtwitter 返回格式: "Fri Feb 14 12:34:56 +0000 2025"
                published_at = datetime.strptime(created_str, "%a %b %d %H:%M:%S %z %Y")
            except:
                pass

        # 提取媒体
        media_urls = []
        media_data = tweet.get("media", {})
        if media_data:
            for m in media_data.get("all", []):
                url = m.get("url")
                if url:
                    media_urls.append(url)

        # 检测转推和回复
        text = tweet.get("text", "")
        is_retweet = text.startswith("RT @")
        is_reply = tweet.get("replying_to") is not None
        reply_to = tweet.get("replying_to")

        if article:
            # X Article 长文章
            return FxTweetContent(
                text=article.get("preview_text", text),
                tweet_url=original_url,
                tweet_id=str(tweet.get("id", "")),
                author_handle=author.get("screen_name", ""),
                author_name=author.get("name", ""),
                published_at=published_at,
                likes=tweet.get("likes", 0),
                retweets=tweet.get("retweets", 0),
                replies=tweet.get("replies", 0),
                views=tweet.get("views", 0),
                bookmarks=tweet.get("bookmarks", 0),
                media_urls=media_urls,
                is_article=True,
                article_title=article.get("title", ""),
                article_content=self._extract_article_content(article),
                article_cover=article.get("cover_media", {}).get("media_info", {}).get("original_img_url"),
                is_retweet=is_retweet,
                is_reply=is_reply,
                reply_to=reply_to,
                source_api="fxtwitter",
            )
        else:
            # 普通推文
            return FxTweetContent(
                text=text,
                tweet_url=original_url,
                tweet_id=str(tweet.get("id", "")),
                author_handle=author.get("screen_name", ""),
                author_name=author.get("name", ""),
                published_at=published_at,
                likes=tweet.get("likes", 0),
                retweets=tweet.get("retweets", 0),
                replies=tweet.get("replies", 0),
                views=tweet.get("views", 0),
                bookmarks=tweet.get("bookmarks", 0),
                media_urls=media_urls,
                is_retweet=is_retweet,
                is_reply=is_reply,
                reply_to=reply_to,
                source_api="fxtwitter",
            )

    def _extract_article_content(self, article: Dict) -> str:
        """
        从 X Article 中提取完整 Markdown 内容

        直接参考 x-fetcher/fetch_x.py 的 extract_article_content()
        """
        if not article:
            return ""

        content_blocks = article.get("content", {}).get("blocks", [])
        paragraphs = []

        for block in content_blocks:
            text = block.get("text", "").strip()
            block_type = block.get("type", "unstyled")

            if not text:
                continue

            # 根据类型添加 Markdown 格式
            if block_type == "header-one":
                paragraphs.append(f"# {text}")
            elif block_type == "header-two":
                paragraphs.append(f"## {text}")
            elif block_type == "header-three":
                paragraphs.append(f"### {text}")
            elif block_type == "blockquote":
                paragraphs.append(f"> {text}")
            elif block_type == "unordered-list-item":
                paragraphs.append(f"- {text}")
            elif block_type == "ordered-list-item":
                paragraphs.append(f"1. {text}")
            else:
                paragraphs.append(text)

        return "\n\n".join(paragraphs)

    # ==================== syndication API (备用) ====================

    async def _fetch_via_syndication(
        self,
        tweet_id: str,
        username: Optional[str] = None,
    ) -> Optional[FxTweetContent]:
        """
        通过 X 官方 syndication API 获取推文 (备用方案)

        参考 x-fetcher/fetch_x.py 的 fetch_via_syndication()
        """
        url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=0"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": self.USER_AGENT},
                )

                if resp.status_code == 200:
                    data = resp.json()
                    return self._parse_syndication_response(data, tweet_id)

        except Exception as e:
            logger.warning(f"[Syndication] API 错误: {e}")

        return None

    def _parse_syndication_response(
        self,
        data: Dict[str, Any],
        tweet_id: str,
    ) -> Optional[FxTweetContent]:
        """解析 syndication API 响应"""
        if not data:
            return None

        user = data.get("user", {})

        # 解析发布时间
        published_at = None
        created_str = data.get("created_at")
        if created_str:
            try:
                published_at = datetime.strptime(created_str, "%a %b %d %H:%M:%S %z %Y")
            except:
                pass

        # 提取媒体
        media_urls = []
        for m in data.get("mediaDetails", []):
            url = m.get("media_url_https")
            if url:
                media_urls.append(url)

        text = data.get("text", "")

        return FxTweetContent(
            text=text,
            tweet_url=f"https://x.com/{user.get('screen_name', 'i')}/status/{tweet_id}",
            tweet_id=tweet_id,
            author_handle=user.get("screen_name", ""),
            author_name=user.get("name", ""),
            published_at=published_at,
            likes=data.get("favorite_count", 0),
            retweets=data.get("retweet_count", 0),
            media_urls=media_urls,
            is_retweet=text.startswith("RT @"),
            source_api="syndication",
        )

    # ==================== 工具方法 ====================

    def _extract_tweet_id(self, url: str) -> Optional[str]:
        """从 URL 提取 tweet ID"""
        patterns = [
            r'(?:x\.com|twitter\.com)/\w+/status/(\d+)',
            r'(?:x\.com|twitter\.com)/\w+/statuses/(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def _extract_username(self, url: str) -> Optional[str]:
        """从 URL 提取用户名"""
        match = re.search(r'(?:x\.com|twitter\.com)/(\w+)/status', url)
        return match.group(1) if match else None

    def to_raw_content(self, item: FxTweetContent, kol: Optional[KOL] = None) -> RawContentItem:
        """
        转换为 RawContentItem（用于聚类流水线）

        兼容现有 TwitterFetcher.to_raw_content() 接口
        """
        # 如果是 X Article，使用完整文章内容
        text = item.article_content if item.is_article and item.article_content else item.text
        title = item.article_title if item.is_article else None

        return RawContentItem(
            text=text,
            source_type="x_kol",
            source_url=item.tweet_url,
            title=title,
            published_at=item.published_at,
            kol_id=kol.id if kol else item.kol_id,
            kol_name=kol.name if kol else item.author_name,
            kol_handle=kol.handle if kol else item.author_handle,
            kol_tier=kol.tier.value if kol and kol.tier else item.kol_tier,
            metrics={
                "likes": item.likes,
                "retweets": item.retweets,
                "replies": item.replies,
                "views": item.views,
                "bookmarks": item.bookmarks,
            },
            media_urls=item.media_urls,
            raw_data={
                "is_retweet": item.is_retweet,
                "is_reply": item.is_reply,
                "reply_to": item.reply_to,
                "is_article": item.is_article,
                "article_title": item.article_title,
                "article_cover": item.article_cover,
                "source_api": item.source_api,
                "kol_weight": kol.weight if kol else item.kol_weight,
            },
        )


# ==================== 便捷函数 ====================

async def fetch_tweet(url: str) -> Optional[FxTweetContent]:
    """便捷函数：抓取单条推文"""
    fetcher = FxTwitterFetcher()
    return await fetcher.fetch_tweet_by_url(url)


async def fetch_tweets_batch(
    urls: List[str],
    concurrency: int = 10,
) -> List[FxTweetContent]:
    """便捷函数：批量抓取推文"""
    fetcher = FxTwitterFetcher()
    return await fetcher.fetch_tweets_by_urls(urls, concurrency)


# ==================== 测试 ====================

async def test_fxtwitter_fetcher():
    """测试 FxTwitter 抓取器"""
    print("=" * 60)
    print("FxTwitter 抓取器测试")
    print("=" * 60)

    fetcher = FxTwitterFetcher()

    # 测试单条推文
    test_urls = [
        "https://x.com/elonmusk/status/1889398567220838725",
        "https://twitter.com/karpathy/status/1889234567890123456",
    ]

    for url in test_urls:
        print(f"\n抓取: {url}")
        content = await fetcher.fetch_tweet_by_url(url)

        if content:
            print(f"  ✅ 成功 via {content.source_api}")
            print(f"  作者: @{content.author_handle} ({content.author_name})")
            print(f"  内容: {content.text[:100]}...")
            print(f"  互动: ❤️ {content.likes} | 🔁 {content.retweets} | 👁️ {content.views}")

            if content.is_article:
                print(f"  📄 X Article: {content.article_title}")
                print(f"  文章长度: {len(content.article_content or '')} 字符")
        else:
            print("  ❌ 抓取失败")


if __name__ == "__main__":
    asyncio.run(test_fxtwitter_fetcher())
