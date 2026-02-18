"""数据模型定义"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Category(Enum):
    """新闻分类"""
    TECH = "科技"
    POLITICS = "政治"
    ECONOMY = "经济"
    SOCIETY = "社会"
    INTERNATIONAL = "国际"
    SPORTS = "体育"
    ENTERTAINMENT = "娱乐"
    OTHER = "其他"


class Region(Enum):
    """新闻区域"""
    CHINA = "中国"
    WORLD = "世界"


@dataclass
class NewsItem:
    """新闻条目"""
    title: str
    url: str
    source_name: str
    region: Region
    published_at: Optional[datetime] = None
    content: str = ""
    summary: str = ""
    category: Category = Category.OTHER

    def to_telegram_message(self) -> str:
        """格式化为 Telegram 消息"""
        category_emoji = {
            Category.TECH: "💻",
            Category.POLITICS: "🏛️",
            Category.ECONOMY: "📈",
            Category.SOCIETY: "👥",
            Category.INTERNATIONAL: "🌍",
            Category.SPORTS: "⚽",
            Category.ENTERTAINMENT: "🎬",
            Category.OTHER: "📰",
        }
        emoji = category_emoji.get(self.category, "📰")

        msg = f"{emoji} [{self.category.value}] {self.title}\n\n"
        if self.summary:
            msg += f"{self.summary}\n\n"
        msg += f"🔗 {self.url}\n"
        msg += f"📍 来源: {self.source_name} ({self.region.value})"
        return msg


@dataclass
class NewsSource:
    """新闻源配置"""
    name: str
    url: str
    region: Region
    source_type: str = "rss"  # rss 或 web
    enabled: bool = True
