"""算法一：原文价值评分

公式：Score = Length_Factor * 0.2 + ln(Likes + 2*Comments + 4*Retweets + 1) * 0.8

长度因子：
- < 50 字：3 分
- 50-200 字：7 分
- > 200 字：10 分

硬过滤规则：
1. 纯图片/视频无正文 → 过滤
2. 字数 < 50 且点赞 < 300 → 过滤
"""
import math
from typing import Optional


def calc_length_factor(text: str) -> int:
    """计算长度因子"""
    length = len(text.strip()) if text else 0
    if length < 50:
        return 3
    elif length <= 200:
        return 7
    else:
        return 10


def calc_value_score(
    text: str,
    likes: int = 0,
    comments: int = 0,
    retweets: int = 0,
) -> float:
    """
    计算帖子价值评分

    公式：Score = Length_Factor * 0.2 + ln(Likes + 2*Comments + 4*Retweets + 1) * 0.8

    Args:
        text: 帖子正文
        likes: 点赞数
        comments: 评论数
        retweets: 转发数

    Returns:
        评分（约 0-15 分）
    """
    # 长度因子
    length_factor = calc_length_factor(text)

    # 互动分（对数衰减）
    # 转发权重 4x，评论权重 2x，点赞权重 1x
    engagement = (likes or 0) + 2 * (comments or 0) + 4 * (retweets or 0)
    engagement_score = math.log(engagement + 1)

    # 最终评分
    score = length_factor * 0.2 + engagement_score * 0.8

    return round(score, 2)


def should_filter(
    text: Optional[str],
    likes: int = 0,
    has_media: bool = False,
) -> tuple[bool, str]:
    """
    判断是否应该过滤掉这条帖子

    硬过滤规则：
    1. 纯图片/视频无正文 → 过滤
    2. 字数 < 50 且点赞 < 300 → 过滤

    Args:
        text: 帖子正文
        likes: 点赞数
        has_media: 是否有媒体（图片/视频）

    Returns:
        (是否过滤, 原因)
    """
    text_length = len(text.strip()) if text else 0

    # 规则1：纯媒体无正文
    if text_length == 0:
        return True, "no_text"

    # 规则2：短文且低互动
    if text_length < 50 and (likes or 0) < 300:
        return True, "short_low_engagement"

    return False, "passed"


# ==================== 便捷函数 ====================

def score_and_filter_posts(posts: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    批量评分和过滤帖子

    Args:
        posts: 帖子列表，每个帖子需要有 text, likes, comments, retweets 字段

    Returns:
        (通过的帖子, 被过滤的帖子)
    """
    passed = []
    filtered = []

    for post in posts:
        text = post.get("text") or post.get("text_content") or ""
        likes = post.get("likes", 0) or 0
        comments = post.get("comments") or post.get("replies", 0) or 0
        retweets = post.get("retweets", 0) or 0
        has_media = bool(post.get("media_urls"))

        # 硬过滤
        should_drop, reason = should_filter(text, likes, has_media)
        if should_drop:
            post["_filter_reason"] = reason
            filtered.append(post)
            continue

        # 计算评分
        score = calc_value_score(text, likes, comments, retweets)
        post["value_score"] = score
        passed.append(post)

    # 按评分排序（高到低）
    passed.sort(key=lambda x: x.get("value_score", 0), reverse=True)

    return passed, filtered
