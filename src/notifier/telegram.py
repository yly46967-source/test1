"""Telegram 推送模块"""
import os
from typing import List, Optional, Dict, Any

from src.logger import get_notifier_logger

logger = get_notifier_logger()

# 尝试导入 telegram 库
try:
    from telegram import Bot
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot 未安装，Telegram 推送功能不可用")


class TelegramNotifier:
    """Telegram 消息推送"""

    # Telegram 单条消息最大 4096 字符
    MAX_MESSAGE_LENGTH = 4000

    # 分类 emoji 映射
    CATEGORY_EMOJI = {
        "model_release": "🚀",
        "funding": "💰",
        "product_launch": "📦",
        "research": "📚",
        "drama": "🎭",
        "tutorial": "📖",
        "market_signal": "📊",
        "news": "📰",
    }

    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.bot = None
        if TELEGRAM_AVAILABLE and self.bot_token:
            self.bot = Bot(token=self.bot_token)

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """发送单条消息"""
        if not self.bot:
            logger.warning("Telegram Bot 未配置")
            return False
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=True
            )
            logger.debug(f"消息发送成功 ({len(text)} 字符)")
            return True
        except Exception as e:
            logger.error(f"消息发送失败: {e}")
            return False

    # ==================== AInsight 情报推送 ====================

    async def send_intelligence(
        self,
        topic_title: str,
        category: str,
        intel_data: Dict[str, Any],
        source_count: int = 0,
        heat_score: int = 0,
    ) -> bool:
        """
        发送情报包

        Args:
            topic_title: 主题标题
            category: 分类
            intel_data: 情报数据，包含 tldr, fact_summary, action_guide, verdict 等
            source_count: 来源数量
            heat_score: 热度分数
        """
        emoji = self.CATEGORY_EMOJI.get(category, "📰")

        msg = f"{emoji} <b>{topic_title}</b>\n\n"

        # TLDR
        if intel_data.get("tldr"):
            msg += f"📌 <b>TLDR</b>\n{intel_data['tldr']}\n\n"

        # 事实摘要
        if intel_data.get("fact_summary"):
            msg += f"📋 <b>事实摘要</b>\n{intel_data['fact_summary']}\n\n"

        # 行动指南
        if intel_data.get("action_guide"):
            msg += f"🎯 <b>行动指南</b>\n{intel_data['action_guide']}\n\n"

        # 结论
        if intel_data.get("verdict"):
            msg += f"⚖️ <b>结论</b>: {intel_data['verdict']}\n\n"

        # 底部信息
        msg += f"─" * 20 + "\n"
        msg += f"📊 来源: {source_count} 条 | 热度: {heat_score}"

        return await self.send_message(msg)

    async def send_topic_summary(
        self,
        topics: List[Dict[str, Any]],
        title: str = "🔥 今日热点主题"
    ) -> bool:
        """
        发送主题摘要列表

        Args:
            topics: 主题列表，每个包含 title, category, source_count, heat_score
            title: 标题
        """
        if not topics:
            return await self.send_message(f"{title}\n\n暂无热点主题")

        msg = f"<b>{title}</b>\n"
        msg += f"共 {len(topics)} 个主题\n"
        msg += "─" * 20 + "\n\n"

        for i, topic in enumerate(topics, 1):
            emoji = self.CATEGORY_EMOJI.get(topic.get("category", ""), "📰")
            msg += f"{i}. {emoji} <b>{topic['title']}</b>\n"
            msg += f"   📊 {topic.get('source_count', 0)} 条来源 | 热度 {topic.get('heat_score', 0)}\n\n"

            # 检查长度
            if len(msg) > self.MAX_MESSAGE_LENGTH - 200:
                msg += f"... 还有 {len(topics) - i} 个主题"
                break

        return await self.send_message(msg)

    async def send_daily_digest(
        self,
        stats: Dict[str, Any],
        top_topics: List[Dict[str, Any]],
        title: str = None
    ) -> bool:
        """
        发送每日情报摘要

        Args:
            stats: 统计数据
            top_topics: 热门主题列表
            title: 标题
        """
        from datetime import datetime

        if title is None:
            now = datetime.now()
            period = "早报" if now.hour < 10 else ("午报" if now.hour < 14 else "晚报")
            title = f"📰 AInsight {now.strftime('%m月%d日')} {period}"

        msg = f"<b>{title}</b>\n"
        msg += "─" * 20 + "\n\n"

        # 统计信息
        msg += "📊 <b>今日统计</b>\n"
        msg += f"• 新增内容: {stats.get('new_contents', 0)} 条\n"
        msg += f"• 活跃主题: {stats.get('active_topics', 0)} 个\n"
        msg += f"• 情报包: {stats.get('intel_packages', 0)} 个\n\n"

        # 热门主题
        if top_topics:
            msg += "🔥 <b>热门主题</b>\n"
            for i, topic in enumerate(top_topics[:5], 1):
                emoji = self.CATEGORY_EMOJI.get(topic.get("category", ""), "📰")
                msg += f"{i}. {emoji} {topic['title']}\n"
            msg += "\n"

        msg += "─" * 20 + "\n"
        msg += "💡 回复 /detail [主题ID] 查看详情"

        return await self.send_message(msg)
