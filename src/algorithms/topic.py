"""算法二：主题提取

为每条帖子提取 1-3 个主题。
主题必须是具体事物/概念（产品名、公司名、技术名、事件名）。

使用 LLM 批量提取，10 条帖子一次调用。
"""
import json
import logging
from typing import Optional
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


# 主题提取 Prompt
TOPIC_EXTRACT_PROMPT = """你是主题提取专家。为每条帖子提取 1-3 个主题。

## 主题要求
- 必须是具体事物或概念（产品名、公司名、技术名、事件名、人名）
- 不要抽象词汇如"创新"、"发展"、"趋势"
- 示例：Openclaw、Claude、GPT-5、马斯克、支付宝创作收益、伊朗局势

## 待提取帖子
{posts}

## 输出格式（只输出 JSON）
{{
  "results": [
    {{"index": 0, "topics": ["主题1", "主题2"]}},
    {{"index": 1, "topics": ["主题1"]}}
  ]
}}"""


async def extract_topics_batch(
    posts: list[dict],
    llm_client: AsyncOpenAI,
    model: str = "qwen-plus",
    batch_size: int = 10,
) -> dict[int, list[str]]:
    """
    批量提取主题

    Args:
        posts: 帖子列表，需要有 text 字段
        llm_client: LLM 客户端
        model: 模型名
        batch_size: 每批处理数量

    Returns:
        {帖子索引: [主题列表]}
    """
    results = {}

    for i in range(0, len(posts), batch_size):
        batch = posts[i:i + batch_size]
        batch_results = await _extract_batch(batch, i, llm_client, model)
        results.update(batch_results)

    return results


async def _extract_batch(
    posts: list[dict],
    start_index: int,
    llm_client: AsyncOpenAI,
    model: str,
) -> dict[int, list[str]]:
    """提取单批帖子的主题"""
    # 格式化帖子
    posts_text = "\n\n".join([
        f"[帖子 {start_index + j}]\n{(p.get('text') or p.get('text_content') or '')[:300]}"
        for j, p in enumerate(posts)
    ])

    prompt = TOPIC_EXTRACT_PROMPT.format(posts=posts_text)

    try:
        response = await llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000,
            response_format={"type": "json_object"}
        )

        data = json.loads(response.choices[0].message.content)
        results = {}

        for item in data.get("results", []):
            idx = item.get("index", 0)
            topics = item.get("topics", [])
            # 清理主题
            topics = [t.strip() for t in topics if t and len(t.strip()) > 0][:3]
            results[idx] = topics

        return results

    except Exception as e:
        logger.warning(f"主题提取失败: {e}")
        # 失败时返回空
        return {start_index + j: [] for j in range(len(posts))}


def group_posts_by_topic(
    posts: list[dict],
    topic_map: dict[int, list[str]],
) -> dict[str, list[dict]]:
    """
    按主题分组帖子

    Args:
        posts: 帖子列表
        topic_map: {帖子索引: [主题列表]}

    Returns:
        {主题名: [帖子列表]}
    """
    groups = {}

    for i, post in enumerate(posts):
        topics = topic_map.get(i, [])
        # 取第一个主题作为主要主题
        if topics:
            main_topic = topics[0]
            if main_topic not in groups:
                groups[main_topic] = []
            groups[main_topic].append(post)

    return groups
