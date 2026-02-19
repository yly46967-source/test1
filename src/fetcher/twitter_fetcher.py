"""X/Twitter RSS 抓取器 - 基于 Nitter 动态网关"""
import asyncio
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from html import unescape

import feedparser

from src.logger import get_logger
from src.database.models import KOL, KOLTierEnum
from .nitter_gateway import get_nitter_gateway, NitterGateway
from .ainsight_fetcher import RawContentItem

logger = get_logger(__name__)


@dataclass
class TwitterContent:
    """Twitter 内容项"""
    text: str
    tweet_url: str
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
    quotes: int = 0

    # 媒体
    media_urls: List[str] = field(default_factory=list)

    # 元数据
    is_retweet: bool = False
    is_reply: bool = False
    reply_to: Optional[str] = None
    raw_html: Optional[str] = None


class TwitterFetcher:
    """X/Twitter 抓取器"""

    def __init__(
        self,
        gateway: Optional[NitterGateway] = None,
        max_items: int = 20,
    ):
        self.gateway = gateway or get_nitter_gateway()
        self.max_items = max_items

    async def fetch_kol(
        self,
        kol: KOL,
        with_replies: bool = False,
    ) -> List[TwitterContent]:
        """
        抓取单个 KOL 的推文

        Args:
            kol: KOL 数据库对象
            with_replies: 是否包含回复

        Returns:
            TwitterContent 列表
        """
        handle = kol.handle.lstrip("@")

        # 通过网关获取 RSS
        rss_content, used_instance = await self.gateway.fetch_rss(
            handle, with_replies=with_replies
        )

        if not rss_content:
            logger.warning(f"[Twitter] @{handle} 抓取失败")
            return []

        # 解析 RSS
        feed = feedparser.parse(rss_content)
        if not feed.entries:
            logger.warning(f"[Twitter] @{handle} 无条目")
            return []

        logger.debug(f"[Twitter] @{handle} 解析到 {len(feed.entries)} 条")

        # 解析条目
        items = []
        for entry in feed.entries[:self.max_items]:
            item = self._parse_entry(entry, kol)
            if item:
                items.append(item)

        return items

    async def fetch_kols_batch(
        self,
        kols: List[KOL],
        concurrency: int = 5,
        with_replies: bool = False,
    ) -> Tuple[List[TwitterContent], Dict[str, int]]:
        """
        批量抓取多个 KOL

        Returns:
            (所有内容, 统计信息)
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch_with_semaphore(kol: KOL):
            async with semaphore:
                return kol.handle, await self.fetch_kol(kol, with_replies)

        tasks = [fetch_with_semaphore(kol) for kol in kols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items = []
        stats = {"success": 0, "failed": 0, "total_items": 0}

        for result in results:
            if isinstance(result, Exception):
                stats["failed"] += 1
                logger.error(f"[Twitter] 抓取异常: {result}")
            else:
                handle, items = result
                if items:
                    all_items.extend(items)
                    stats["success"] += 1
                    stats["total_items"] += len(items)
                    logger.info(f"[Twitter] @{handle} 抓取 {len(items)} 条")
                else:
                    stats["failed"] += 1

        return all_items, stats

    async def fetch_search(
        self,
        query: str,
    ) -> List[TwitterContent]:
        """
        搜索推文

        Args:
            query: 搜索关键词

        Returns:
            TwitterContent 列表
        """
        rss_content, _ = await self.gateway.fetch_search(query)

        if not rss_content:
            return []

        feed = feedparser.parse(rss_content)
        items = []

        for entry in feed.entries[:self.max_items]:
            item = self._parse_search_entry(entry)
            if item:
                items.append(item)

        return items

    def _parse_entry(
        self,
        entry: Any,
        kol: KOL,
    ) -> Optional[TwitterContent]:
        """解析 Nitter RSS 条目"""
        try:
            # 基础字段
            title = entry.get("title", "")
            link = entry.get("link", "")

            if not link:
                return None

            # 发布时间
            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published_at = datetime(*entry.published_parsed[:6])

            # 内容
            content_html = ""
            if hasattr(entry, "summary"):
                content_html = entry.summary
            elif hasattr(entry, "description"):
                content_html = entry.description

            # 清理文本
            text = self._clean_nitter_html(content_html)

            # 检测是否是转推
            is_retweet = text.startswith("RT @") or "retweeted" in title.lower()

            # 检测是否是回复
            is_reply = False
            reply_to = None
            if text.startswith("@"):
                is_reply = True
                match = re.match(r"@(\w+)", text)
                if match:
                    reply_to = match.group(1)

            # 提取互动数据
            metrics = self._extract_metrics(content_html)

            # 提取媒体
            media_urls = self._extract_media(entry, content_html)

            return TwitterContent(
                text=text,
                tweet_url=link,
                author_handle=kol.handle,
                author_name=kol.name,
                published_at=published_at,
                kol_id=kol.id,
                kol_tier=kol.tier.value if kol.tier else None,
                kol_weight=kol.weight or 1.0,
                likes=metrics.get("likes", 0),
                retweets=metrics.get("retweets", 0),
                replies=metrics.get("replies", 0),
                quotes=metrics.get("quotes", 0),
                media_urls=media_urls,
                is_retweet=is_retweet,
                is_reply=is_reply,
                reply_to=reply_to,
                raw_html=content_html,
            )

        except Exception as e:
            logger.warning(f"[Twitter] 解析条目失败: {e}")
            return None

    def _parse_search_entry(self, entry: Any) -> Optional[TwitterContent]:
        """解析搜索结果条目"""
        try:
            link = entry.get("link", "")
            if not link:
                return None

            # 从链接提取 handle
            match = re.search(r"twitter\.com/(\w+)/status", link)
            if not match:
                match = re.search(r"nitter\.[^/]+/(\w+)/status", link)
            handle = match.group(1) if match else "unknown"

            content_html = entry.get("summary", "") or entry.get("description", "")
            text = self._clean_nitter_html(content_html)

            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published_at = datetime(*entry.published_parsed[:6])

            return TwitterContent(
                text=text,
                tweet_url=link,
                author_handle=handle,
                published_at=published_at,
                media_urls=self._extract_media(entry, content_html),
            )

        except Exception as e:
            logger.warning(f"[Twitter] 解析搜索条目失败: {e}")
            return None

    def _clean_nitter_html(self, html: str) -> str:
        """清理 Nitter HTML"""
        if not html:
            return ""

        # 移除 Nitter 特有的元素
        html = re.sub(r'<div class="quote[^"]*">.*?</div>', '', html, flags=re.DOTALL)

        # 将链接转换为文本
        html = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', r'\2 (\1)', html)

        # 将块级元素转换为换行
        html = re.sub(r'</(p|div|br)>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)

        # 移除所有 HTML 标签
        text = re.sub(r'<[^>]+>', '', html)

        # 解码 HTML 实体
        text = unescape(text)

        # 清理空白
        lines = text.split('\n')
        lines = [re.sub(r'\s+', ' ', line).strip() for line in lines]
        lines = [line for line in lines if line]

        return '\n'.join(lines)

    def _extract_metrics(self, html: str) -> Dict[str, int]:
        """提取互动数据"""
        metrics = {}

        patterns = {
            "likes": r'(\d+)\s*(?:likes?|❤️|♥)',
            "retweets": r'(\d+)\s*(?:retweets?|🔁|RT)',
            "replies": r'(\d+)\s*(?:replies?|💬|comments?)',
            "quotes": r'(\d+)\s*(?:quotes?)',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                try:
                    metrics[key] = int(match.group(1))
                except ValueError:
                    pass

        return metrics

    def _extract_media(self, entry: Any, html: str) -> List[str]:
        """提取媒体链接"""
        media_urls = []

        # 从 enclosures 提取
        if hasattr(entry, "enclosures"):
            for enc in entry.enclosures:
                url = enc.get("href", "")
                if url and url not in media_urls:
                    media_urls.append(url)

        # 从 media_content 提取
        if hasattr(entry, "media_content"):
            for media in entry.media_content:
                url = media.get("url", "")
                if url and url not in media_urls:
                    media_urls.append(url)

        # 从 HTML 提取图片
        img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html)
        for url in img_urls:
            if url not in media_urls and not url.endswith(".svg"):
                media_urls.append(url)

        # 从 HTML 提取视频
        video_urls = re.findall(r'<video[^>]+src=["\']([^"\']+)["\']', html)
        media_urls.extend([u for u in video_urls if u not in media_urls])

        return media_urls[:5]

    def to_raw_content(self, item: TwitterContent) -> RawContentItem:
        """转换为 RawContentItem（用于聚类流水线）"""
        return RawContentItem(
            text=item.text,
            source_type="x_kol",
            source_url=item.tweet_url,
            title=None,
            published_at=item.published_at,
            kol_id=item.kol_id,
            kol_name=item.author_name,
            kol_handle=item.author_handle,
            kol_tier=item.kol_tier,
            metrics={
                "likes": item.likes,
                "retweets": item.retweets,
                "replies": item.replies,
            },
            media_urls=item.media_urls,
            raw_data={
                "is_retweet": item.is_retweet,
                "is_reply": item.is_reply,
                "reply_to": item.reply_to,
                "kol_weight": item.kol_weight,
            },
        )


async def fetch_twitter_kols(
    kols: List[KOL],
    concurrency: int = 5,
    with_replies: bool = False,
) -> Tuple[List[RawContentItem], Dict[str, int]]:
    """
    便捷函数：抓取 KOL 推文并转换为 RawContentItem

    Args:
        kols: KOL 列表
        concurrency: 并发数
        with_replies: 是否包含回复

    Returns:
        (RawContentItem 列表, 统计信息)
    """
    fetcher = TwitterFetcher()
    items, stats = await fetcher.fetch_kols_batch(
        kols, concurrency=concurrency, with_replies=with_replies
    )

    # 转换为 RawContentItem
    raw_items = [fetcher.to_raw_content(item) for item in items]

    return raw_items, stats


async def test_twitter_fetcher():
    """测试 Twitter 抓取器"""
    from src.database.models import KOL, KOLTierEnum

    print("=" * 60)
    print("Twitter 抓取器测试")
    print("=" * 60)

    # 创建测试 KOL
    test_kols = [
        KOL(id=1, handle="elonmusk", name="Elon Musk", tier=KOLTierEnum.GOD, weight=10.0),
        KOL(id=2, handle="karpathy", name="Andrej Karpathy", tier=KOLTierEnum.GOD, weight=10.0),
    ]

    fetcher = TwitterFetcher(max_items=5)

    for kol in test_kols:
        print(f"\n抓取 @{kol.handle}...")
        items = await fetcher.fetch_kol(kol)

        if items:
            print(f"  ✅ 获取 {len(items)} 条推文")
            for i, item in enumerate(items[:2], 1):
                print(f"\n  [{i}] {item.text[:100]}...")
                print(f"      ❤️ {item.likes} | 🔁 {item.retweets}")
        else:
            print("  ❌ 抓取失败")

    # 测试搜索
    print("\n\n搜索 'GPT-5'...")
    search_results = await fetcher.fetch_search("GPT-5")
    print(f"  找到 {len(search_results)} 条结果")


if __name__ == "__main__":
    asyncio.run(test_twitter_fetcher())
