"""AI 总结器"""
import os
from typing import List
from openai import OpenAI

from src.models import NewsItem


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
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"总结失败: {e}")
            return ""

    async def summarize_batch(self, items: List[NewsItem]) -> List[NewsItem]:
        """批量总结新闻"""
        for item in items:
            item.summary = await self.summarize(item)
        return items
