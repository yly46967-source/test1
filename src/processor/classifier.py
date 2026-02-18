"""AI 分类器"""
import os
from typing import List
from openai import OpenAI

from src.models import NewsItem, Category


class Classifier:
    """使用 DashScope API 分类新闻"""

    CATEGORIES = ["科技", "政治", "经济", "社会", "国际", "体育", "娱乐", "其他"]

    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        self.model = os.getenv("DASHSCOPE_MODEL", "qwen-plus")

    def _parse_category(self, text: str) -> Category:
        """解析分类结果"""
        text = text.strip()
        category_map = {
            "科技": Category.TECH,
            "政治": Category.POLITICS,
            "经济": Category.ECONOMY,
            "社会": Category.SOCIETY,
            "国际": Category.INTERNATIONAL,
            "体育": Category.SPORTS,
            "娱乐": Category.ENTERTAINMENT,
        }
        return category_map.get(text, Category.OTHER)

    async def classify(self, item: NewsItem) -> Category:
        """分类单条新闻"""
        prompt = f"""请将以下新闻分类到一个类别中。

类别选项：{', '.join(self.CATEGORIES)}

新闻标题：{item.title}
新闻内容：{item.content[:500] if item.content else '无'}

只输出类别名称，不要其他内容。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=20,
                messages=[{"role": "user", "content": prompt}]
            )
            return self._parse_category(response.choices[0].message.content)
        except Exception as e:
            print(f"分类失败: {e}")
            return Category.OTHER

    async def classify_batch(self, items: List[NewsItem]) -> List[NewsItem]:
        """批量分类新闻"""
        for item in items:
            item.category = await self.classify(item)
        return items
