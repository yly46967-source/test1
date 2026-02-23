"""情报合成引擎 - 简化版

核心功能：
1. 多源信息聚合
2. 事实/推测区分
3. 来源追溯
"""
import json
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

from openai import AsyncOpenAI
from src.logger import get_logger

logger = get_logger(__name__)


class ValueLevel(Enum):
    """内容价值等级"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    REJECT = "reject"


@dataclass
class SynthesisResult:
    """合成结果"""
    success: bool
    intel_id: str
    synthesis: Optional[Dict[str, Any]] = None
    value_level: ValueLevel = ValueLevel.MEDIUM
    source_count: int = 0
    kol_count: int = 0
    error: Optional[str] = None


# 合成 Prompt
SYNTHESIS_PROMPT = """你是 AI 情报分析师。基于多个来源合成情报摘要。

## 输入来源
{sources}

## 输出要求（JSON 格式）

```json
{{
  "value_level": "high/medium/low/reject",
  "value_reason": "价值判断理由",
  "tldr": "一句话结论（≤50字）",
  "verified_facts": [
    {{"fact": "已验证事实", "sources": [1, 2], "confidence": "high/medium"}}
  ],
  "analysis": {{
    "implications": ["推断1 [推测]", "推断2"],
    "uncertainties": ["不确定点"]
  }},
  "action_guide": {{
    "for_developers": ["行动建议"],
    "watch_list": ["关注点"]
  }},
  "verdict": {{
    "impact": "paradigm_shift/significant/incremental/noise",
    "urgency": "act_now/watch/background",
    "note": "分析师点评（≤100字）"
  }}
}}
```

## 规则
1. verified_facts 中的事实必须有来源支持
2. 单一来源的信息标注 confidence: medium
3. 推测性内容必须加 [推测] 标签
4. value_level 为 reject 时其他字段可省略
5. 只输出 JSON，不要其他内容"""


class SynthesisEngine:
    """情报合成引擎"""

    def __init__(
        self,
        llm_client: AsyncOpenAI,
        model: str = "qwen-plus",
        reject_low_value: bool = True,
    ):
        self.llm = llm_client
        self.model = model
        self.reject_low_value = reject_low_value

    async def synthesize(
        self,
        topic_title: str,
        sources: List[Dict[str, Any]],
        topic_id: Optional[int] = None,
    ) -> SynthesisResult:
        """
        合成情报包

        Args:
            topic_title: 主题标题
            sources: 来源列表，每个包含 source_id, text, kol_handle 等
            topic_id: 主题 ID

        Returns:
            SynthesisResult
        """
        if not sources:
            return SynthesisResult(
                success=False,
                intel_id="",
                value_level=ValueLevel.REJECT,
                error="没有来源"
            )

        intel_id = self._generate_intel_id(topic_title, topic_id)
        kol_handles = set(s.get("kol_handle") for s in sources if s.get("kol_handle"))

        # 构建来源文本
        sources_text = self._format_sources(sources)
        prompt = SYNTHESIS_PROMPT.format(sources=sources_text)

        try:
            response = await self.llm.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2000,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)

            # 解析价值等级
            value_str = result.get("value_level", "medium")
            value_level = self._parse_value_level(value_str)

            # 检查是否拒绝
            if value_level == ValueLevel.REJECT:
                return SynthesisResult(
                    success=False,
                    intel_id=intel_id,
                    value_level=value_level,
                    source_count=len(sources),
                    kol_count=len(kol_handles),
                    error=result.get("value_reason", "内容价值过低")
                )

            if self.reject_low_value and value_level == ValueLevel.LOW:
                return SynthesisResult(
                    success=False,
                    intel_id=intel_id,
                    value_level=value_level,
                    source_count=len(sources),
                    kol_count=len(kol_handles),
                    error=f"低价值: {result.get('value_reason', '')}"
                )

            # 构建合成结果
            synthesis = {
                "tldr": result.get("tldr", ""),
                "fact_summary": {
                    "verified_facts": result.get("verified_facts", []),
                },
                "action_guide": result.get("action_guide", {}),
                "logic_chain": result.get("analysis", {}).get("implications", []),
                "verdict": result.get("verdict", {}),
                "source_count": len(sources),
                "kol_count": len(kol_handles),
                "value_level": value_level.value,
            }

            logger.info(f"情报合成成功: {intel_id}")

            return SynthesisResult(
                success=True,
                intel_id=intel_id,
                synthesis=synthesis,
                value_level=value_level,
                source_count=len(sources),
                kol_count=len(kol_handles)
            )

        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}")
            return SynthesisResult(
                success=False,
                intel_id=intel_id,
                source_count=len(sources),
                kol_count=len(kol_handles),
                error=f"JSON 解析失败: {e}"
            )
        except Exception as e:
            logger.error(f"合成失败: {e}")
            return SynthesisResult(
                success=False,
                intel_id=intel_id,
                source_count=len(sources),
                kol_count=len(kol_handles),
                error=str(e)
            )

    def _format_sources(self, sources: List[Dict]) -> str:
        """格式化来源"""
        lines = []
        for i, s in enumerate(sources, 1):
            kol = s.get("kol_handle", "unknown")
            tier = s.get("kol_tier", "observer")
            text = (s.get("text", "") or s.get("text_content", ""))[:500]
            lines.append(f"[来源 {i}] @{kol} ({tier})\n{text}\n")
        return "\n".join(lines)

    def _parse_value_level(self, level_str: str) -> ValueLevel:
        """解析价值等级"""
        mapping = {
            "high": ValueLevel.HIGH,
            "medium": ValueLevel.MEDIUM,
            "low": ValueLevel.LOW,
            "reject": ValueLevel.REJECT,
        }
        return mapping.get(level_str.lower(), ValueLevel.MEDIUM)

    def _generate_intel_id(self, title: str, topic_id: Optional[int]) -> str:
        """生成情报 ID"""
        date_str = datetime.now().strftime("%Y%m%d")
        slug = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', title)[:15].lower() or "intel"
        if topic_id:
            return f"intel_{date_str}_{topic_id}"
        return f"intel_{date_str}_{slug}"


async def synthesize_topic(
    llm_client: AsyncOpenAI,
    topic_id: int,
    topic_title: str,
    raw_contents: List[Any],
    model: str = "qwen-plus",
) -> SynthesisResult:
    """便捷函数：合成主题情报"""
    sources = []
    for c in raw_contents:
        sources.append({
            "source_id": c.id,
            "text": c.text_content,
            "kol_handle": c.author_handle or "",
            "kol_tier": c.raw_data.get("kol_tier", "observer") if c.raw_data else "observer",
            "published_at": c.published_at.isoformat() if c.published_at else "",
        })

    engine = SynthesisEngine(llm_client, model)
    return await engine.synthesize(topic_title, sources, topic_id)
