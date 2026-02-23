"""算法三：情报生成

以"机会发现者"视角生成三段式情报：
1. 核心信号 (The Signal) - 3句话说清新变量
2. 利益重构 (The Stakeholder Shift) - 谁获利？谁受损？
3. 行动灵感 (The Alpha Opportunity) - 2-3个可操作方向
"""
import json
from dataclasses import dataclass
from typing import Optional
from openai import AsyncOpenAI


@dataclass
class Intel:
    """情报结构"""
    topic: str              # 主题
    title: str              # 情报标题
    signal: str             # 核心信号
    shift: str              # 利益重构
    alpha: list[str]        # 行动灵感
    source_posts: list[dict]  # 来源帖子
    source_count: int       # 来源数量


# 情报生成 Prompt
INTEL_PROMPT = """你是机会发现者。基于以下帖子生成情报。

## 主题：{topic}

## 相关帖子
{posts}

## 输出要求
以"机会发现者"视角提炼：这些信息对什么人群、在什么领域、可能产生什么具体影响？

## 输出格式（只输出 JSON）
{{
  "title": "情报标题（10字内，吸引眼球）",
  "signal": "核心信号：3句话说清新变量，必须包含具体事物名",
  "shift": "利益重构：谁获利？谁的护城河正在崩塌？",
  "alpha": ["行动灵感1：具体可操作的实验方向", "行动灵感2"]
}}

## 注意
- 不要简单总结帖子内容
- 要挖掘背后的机��和影响
- 行动灵感要具体、可执行"""


async def generate_intel(
    topic: str,
    posts: list[dict],
    llm_client: AsyncOpenAI,
    model: str = "qwen-plus",
) -> Optional[Intel]:
    """
    为单个主题生成情报

    Args:
        topic: 主题名
        posts: 该主题下的帖子列表
        llm_client: LLM 客户端
        model: 模型名

    Returns:
        Intel 对象，失败返回 None
    """
    if not posts:
        return None

    # 格式化帖子
    posts_text = "\n\n".join([
        f"[帖子 {i+1}] @{p.get('author_handle', 'unknown')}\n{(p.get('text') or p.get('text_content') or '')[:400]}"
        for i, p in enumerate(posts[:10])  # 最多 10 条
    ])

    prompt = INTEL_PROMPT.format(topic=topic, posts=posts_text)

    try:
        response = await llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=800,
            response_format={"type": "json_object"}
        )

        data = json.loads(response.choices[0].message.content)

        return Intel(
            topic=topic,
            title=data.get("title", topic),
            signal=data.get("signal", ""),
            shift=data.get("shift", ""),
            alpha=data.get("alpha", []),
            source_posts=posts,
            source_count=len(posts),
        )

    except Exception as e:
        print(f"情报生成失败 [{topic}]: {e}")
        return None


async def generate_intels_for_topics(
    topic_groups: dict[str, list[dict]],
    llm_client: AsyncOpenAI,
    model: str = "qwen-plus",
    min_posts: int = 2,
) -> list[Intel]:
    """
    为多个主题生成情报

    Args:
        topic_groups: {主题名: [帖子列表]}
        llm_client: LLM 客户端
        model: 模型名
        min_posts: 最少帖子数（少于此数不生成情报）

    Returns:
        情报列表
    """
    intels = []

    # 按帖子数排序，优先处理热门主题
    sorted_topics = sorted(
        topic_groups.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )

    for topic, posts in sorted_topics:
        if len(posts) < min_posts:
            continue

        intel = await generate_intel(topic, posts, llm_client, model)
        if intel:
            intels.append(intel)

    return intels
