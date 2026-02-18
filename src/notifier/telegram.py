"""Telegram 推送模块"""
import os
from typing import List
from telegram import Bot

from src.models import NewsItem, Category


class TelegramNotifier:
    """Telegram 消息推送"""

    # Telegram 单条消息最大 4096 字符
    MAX_MESSAGE_LENGTH = 4000

    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.bot = Bot(token=self.bot_token)

    async def send_message(self, text: str) -> bool:
        """发送单条消息"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return True
        except Exception as e:
            print(f"发送失败: {e}")
            return False

    async def send_news(self, item: NewsItem) -> bool:
        """发送单条新闻"""
        return await self.send_message(item.to_telegram_message())

    async def send_digest(self, items: List[NewsItem], title: str = "📰 新闻摘要") -> bool:
        """发送新闻摘要，自动分页"""
        if not items:
            return await self.send_message(f"{title}\n\n暂无新闻")

        # 按分类分组
        by_category = {}
        for item in items:
            cat = item.category
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(item)

        # 构建消息列表（可能需要分多条发送）
        messages = []
        current_msg = f"<b>{title}</b>\n"
        current_msg += f"共 {len(items)} 条新闻\n"
        current_msg += "─" * 20 + "\n\n"

        for category in Category:
            if category not in by_category:
                continue
            cat_items = by_category[category]

            section = f"<b>{category.value}</b> ({len(cat_items)})\n"
            for item in cat_items:
                section += f"• {item.title}\n"
                if item.summary:
                    section += f"  {item.summary}\n"
                section += f"  🔗 {item.source_name}\n\n"

            # 检查是否超长，需要分页
            if len(current_msg) + len(section) > self.MAX_MESSAGE_LENGTH:
                messages.append(current_msg)
                current_msg = f"<b>{title} (续)</b>\n\n"

            current_msg += section

        if current_msg.strip():
            messages.append(current_msg)

        # 发送所有消息
        success = True
        for msg in messages:
            if not await self.send_message(msg):
                success = False

        return success
