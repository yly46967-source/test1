"""内容过滤器 - 聚类前置过滤

两层过滤：
1. 规则过滤（零成本）- 过滤垃圾、广告、无意义内容
2. AI评分过滤（可选）- 评估内容价值
"""
import re
from dataclasses import dataclass
from typing import List, Tuple, Optional
from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FilterResult:
    """过滤结果"""
    passed: bool
    reason: str
    score: Optional[dict] = None  # AI评分结果


class ContentFilter:
    """内容过滤器"""

    # 垃圾模式（正则）
    SPAM_PATTERNS = [
        r'giveaway|airdrop|free\s+\$|whitelist',  # 空投垃圾
        r'follow.*retweet.*win|rt.*to.*win',       # 抽奖
        r'dm\s+me|link\s+in\s+bio|check\s+bio',    # 引流
        r'(🚀|💰|🔥|💎|🌙){3,}',                    # emoji spam
        r'#ad\b|#sponsored|#promo',                # 广告标记
        r'join\s+(our\s+)?discord|telegram\s+group', # 社群引流
    ]

    # 低价值模式
    LOW_VALUE_PATTERNS = [
        r'^(gm|gn|good\s+(morning|night))\s*[!.]*$',  # 纯问候
        r'^(lol|lmao|haha|😂+)\s*$',                   # 纯表情
        r'^\s*@\w+\s*$',                               # 纯@
        r'^(yes|no|ok|nice|cool|great|wow)\s*[!.]*$', # 单词回复
    ]

    # 配置
    MIN_TEXT_LENGTH = 30           # 最短文本长度
    MAX_HASHTAG_RATIO = 0.4        # 最大 hashtag 占比
    MIN_ALPHA_RATIO = 0.3          # 最小字母/汉字占比

    def __init__(
        self,
        min_length: int = 30,
        enable_ai_scoring: bool = False,
        min_ai_score: int = 15,
    ):
        self.min_length = min_length
        self.enable_ai_scoring = enable_ai_scoring
        self.min_ai_score = min_ai_score

    def filter(self, content: dict) -> FilterResult:
        """
        过滤单条内容

        Args:
            content: 包含 text, source_type 等字段

        Returns:
            FilterResult
        """
        text = content.get("text", "") or content.get("text_content", "")

        # 1. 长度检查
        if len(text.strip()) < self.min_length:
            return FilterResult(False, "too_short")

        # 2. 垃圾模式检查
        for pattern in self.SPAM_PATTERNS:
            if re.search(pattern, text, re.I):
                return FilterResult(False, f"spam:{pattern[:15]}")

        # 3. 低价值模式检查
        for pattern in self.LOW_VALUE_PATTERNS:
            if re.match(pattern, text.strip(), re.I):
                return FilterResult(False, f"low_value:{pattern[:15]}")

        # 4. Hashtag 占比检查
        hashtags = re.findall(r'#\w+', text)
        words = text.split()
        if words and len(hashtags) / len(words) > self.MAX_HASHTAG_RATIO:
            return FilterResult(False, "hashtag_spam")

        # 5. 有效字符占比检查
        alpha_chars = len(re.findall(r'[a-zA-Z\u4e00-\u9fff]', text))
        if len(text) > 0 and alpha_chars / len(text) < self.MIN_ALPHA_RATIO:
            return FilterResult(False, "low_alpha_ratio")

        # 6. 纯转发检查（RT 开头且无额外内容）
        if text.strip().startswith('RT @') and len(text) < 200:
            # 检查是否只是转发没有评论
            rt_match = re.match(r'^RT @\w+:\s*', text)
            if rt_match and len(text) - len(rt_match.group()) < 20:
                return FilterResult(False, "pure_retweet")

        return FilterResult(True, "passed")

    def filter_batch(
        self,
        contents: List[dict]
    ) -> Tuple[List[dict], List[dict]]:
        """
        批量过滤

        Returns:
            (passed_contents, filtered_contents)
        """
        passed = []
        filtered = []

        for content in contents:
            result = self.filter(content)
            if result.passed:
                passed.append(content)
            else:
                content["_filter_reason"] = result.reason
                filtered.append(content)

        logger.info(f"过滤结果: {len(passed)} 通过, {len(filtered)} 过滤")
        return passed, filtered

    def get_quality_score(self, content: dict) -> int:
        """
        计算内容质量分数（简化版，不调用 LLM）

        评分维度：
        - 长度分 (0-3): 越长越好
        - 互动分 (0-3): likes/retweets/replies
        - KOL分 (0-2): 根据 tier
        - 内容分 (0-2): 是否包含链接、代码、数据

        Returns:
            0-10 分数
        """
        text = content.get("text", "") or content.get("text_content", "")

        score = 0

        # 长度分
        text_len = len(text)
        if text_len > 500:
            score += 3
        elif text_len > 200:
            score += 2
        elif text_len > 100:
            score += 1

        # 互动分
        likes = content.get("likes", 0) or 0
        retweets = content.get("retweets", 0) or 0
        replies = content.get("replies", 0) or 0
        engagement = likes + retweets * 2 + replies

        if engagement > 1000:
            score += 3
        elif engagement > 100:
            score += 2
        elif engagement > 10:
            score += 1

        # KOL 分
        kol_tier = content.get("kol_tier", "observer")
        if isinstance(kol_tier, str):
            tier_scores = {"god": 2, "expert": 2, "insider": 1, "observer": 0}
            score += tier_scores.get(kol_tier.lower(), 0)

        # 内容分
        has_link = bool(re.search(r'https?://', text))
        has_code = bool(re.search(r'```|`[^`]+`', text))
        has_numbers = bool(re.search(r'\d+[%$MBK]|\$\d+', text))

        if has_link:
            score += 1
        if has_code or has_numbers:
            score += 1

        return min(score, 10)


# 便捷函数
def filter_contents(
    contents: List[dict],
    min_length: int = 30,
) -> Tuple[List[dict], List[dict]]:
    """便捷函数：过滤内容列表"""
    f = ContentFilter(min_length=min_length)
    return f.filter_batch(contents)
