"""抓取器基类"""
from abc import ABC, abstractmethod
from typing import List
from src.models import NewsItem, NewsSource


class BaseFetcher(ABC):
    """新闻抓取器基类"""

    def __init__(self, source: NewsSource):
        self.source = source

    @abstractmethod
    async def fetch(self) -> List[NewsItem]:
        """抓取新闻列表"""
        pass
