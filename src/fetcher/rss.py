"""RSS 抓取器"""
from datetime import datetime
from typing import List
import feedparser
import httpx

from src.models import NewsItem, NewsSource
from src.fetcher.base import BaseFetcher
from src.logger import get_fetcher_logger

logger = get_fetcher_logger()


class RSSFetcher(BaseFetcher):
    """RSS Feed 抓取器（支持重试）"""

    # 需要重试的异常类型
    RETRYABLE_EXCEPTIONS = (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.ConnectTimeout,
    )

    def __init__(
        self,
        source: NewsSource,
        max_items: int = 10,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        super().__init__(source)
        self.max_items = max_items
        self.timeout = timeout
        self.max_retries = max_retries

    async def _fetch_with_retry(self) -> str:
        """带重试的 HTTP 请求"""
        last_exception = None
        delay = 1.0

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(
                        self.source.url,
                        headers={"User-Agent": "NewsFunnel/1.0"},
                        follow_redirects=True
                    )
                    response.raise_for_status()
                    return response.text

            except self.RETRYABLE_EXCEPTIONS as e:
                last_exception = e
                if attempt < self.max_retries:
                    logger.warning(
                        f"[{self.source.name}] 请求失败，重试 {attempt + 1}/{self.max_retries}: {type(e).__name__}"
                    )
                    import asyncio
                    await asyncio.sleep(delay)
                    delay *= 2  # 指数退避

            except httpx.HTTPStatusError as e:
                # HTTP 错误不重试（4xx, 5xx）
                logger.warning(f"[{self.source.name}] HTTP 错误: {e.response.status_code}")
                return None

        # 所有重试都失败
        logger.error(f"[{self.source.name}] 重试 {self.max_retries} 次后仍失败: {last_exception}")
        return None

    async def fetch(self) -> List[NewsItem]:
        """抓取 RSS feed"""
        items = []

        try:
            # 带重试的请求
            content = await self._fetch_with_retry()
            if content is None:
                return items

            # 解析 RSS
            feed = feedparser.parse(content)
            logger.debug(f"[{self.source.name}] 解析到 {len(feed.entries)} 条条目")

            for entry in feed.entries[: self.max_items]:
                published_at = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published_at = datetime(*entry.published_parsed[:6])

                content = ""
                if hasattr(entry, "summary"):
                    content = entry.summary
                elif hasattr(entry, "description"):
                    content = entry.description

                item = NewsItem(
                    title=entry.get("title", "无标题"),
                    url=entry.get("link", ""),
                    source_name=self.source.name,
                    region=self.source.region,
                    published_at=published_at,
                    content=content,
                )
                items.append(item)

        except Exception as e:
            logger.error(f"[{self.source.name}] 解析失败: {e}")

        return items
