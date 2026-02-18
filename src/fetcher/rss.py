"""RSS 抓取器"""
from datetime import datetime
from typing import List
import feedparser
import httpx

from src.models import NewsItem, NewsSource
from src.fetcher.base import BaseFetcher


class RSSFetcher(BaseFetcher):
    """RSS Feed 抓取器"""

    def __init__(self, source: NewsSource, max_items: int = 10, timeout: int = 30):
        super().__init__(source)
        self.max_items = max_items
        self.timeout = timeout

    async def fetch(self) -> List[NewsItem]:
        """抓取 RSS feed"""
        items = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    self.source.url,
                    headers={"User-Agent": "NewsFunnel/1.0"},
                    follow_redirects=True
                )
                response.raise_for_status()

            feed = feedparser.parse(response.text)

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
            print(f"[{self.source.name}] 抓取失败: {e}")

        return items
