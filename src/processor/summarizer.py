"""AI 总结器"""
import os
from typing import List
from openai import OpenAI

from src.models import NewsItem
from src.logger import get_processor_logger

logger = get_processor_logger()


class Summarizer:
    """使用 DashScope API 总结新闻"""

    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        self.model = os.getenv("DASHSCOPE_MODEL", "qwen-plus")

    async def summarize(self, item: NewsItem) -> str:
        """总结单条新闻"""
        if not item.content:
            return ""

        prompt = f"""请用1-2句话简洁总结以下新闻的核心内容，使用中文：

标题：{item.title}
内容：{item.content[:2000]}

只输出总结，不要其他内容。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            summary = response.choices[0].message.content.strip()
            logger.debug(f"总结完成: {item.title[:30]}...")
            return summary
        except Exception as e:
            logger.error(f"总结失败 [{item.title[:30]}...]: {e}")
            return ""

    async def summarize_batch(self, items: List[NewsItem]) -> List[NewsItem]:
        """批量总结新闻"""
        logger.info(f"开始总结 {len(items)} 条新闻")
        for i, item in enumerate(items, 1):
            item.summary = await self.summarize(item)
            if i % 10 == 0:
                logger.debug(f"总结进度: {i}/{len(items)}")
        logger.info(f"总结完成: {len(items)} 条")
        return items
