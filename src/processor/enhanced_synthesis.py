"""
增强版情报合成引擎 - XML 封装 + 低价值拒绝 + 来源映射

核心改进：
1. XML 结构化输入 - 更清晰的来源标记，便于 LLM 理解
2. 低价值拒绝机制 - 自动识别并拒绝合成低价值内容
3. 1:1 来源映射 - 输出中包含 source_id，可追溯到原始内容
4. KOL 权重加权 - 高权重 KOL 观点优先采信
"""
import json
import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

from openai import AsyncOpenAI

from src.logger import get_logger

logger = get_logger(__name__)


class ValueLevel(Enum):
    """内容价值等级"""
    HIGH = "high"           # 高价值：独家信息、重大发布
    MEDIUM = "medium"       # 中等价值：有用但非独家
    LOW = "low"             # 低价值：重复、营销、水文
    REJECT = "reject"       # 拒绝合成：纯噪音


@dataclass
class SourceMapping:
    """来源映射"""
    source_id: int              # 原始内容 ID
    kol_handle: str             # KOL handle
    kol_tier: str               # KOL 等级
    weight: float               # 权重
    contribution: str           # 贡献描述
    cited_in: List[str] = field(default_factory=list)  # 被引用的字段


@dataclass
class EnhancedSynthesisResult:
    """增强版合成结果"""
    success: bool
    intel_id: str
    synthesis: Optional[Dict[str, Any]]
    source_count: int
    kol_count: int
    value_level: ValueLevel
    source_mappings: List[SourceMapping]
    rejection_reason: Optional[str] = None
    error: Optional[str] = None


# XML 格式的合成 System Prompt
ENHANCED_SYNTHESIS_PROMPT = """你是 AInsight Pro 的首席情报分析师。

## 输入格式
你将收到 XML 格式的原始信息，每条信息包含：
- source_id: 来源唯一标识（用于追溯）
- kol_handle: KOL 账号
- kol_tier: KOL 等级 (god/expert/insider/observer)
- weight: 权重分数
- content: 内容文本

## 任务
1. 首先评估这批信息的整体价值
2. 如果价值过低，直接拒绝合成
3. 如果值得合成，生成结构化情报包

## 价值评估标准
- **HIGH**: 包含独家信息、重大发布、技术突破
- **MEDIUM**: 有用信息但非独家，或多个来源交叉验证
- **LOW**: 大部分是重复信息或营销内容
- **REJECT**: 纯噪音、无实质内容、全是水文

## 输出 JSON 结构

```json
{
  "value_assessment": {
    "level": "high/medium/low/reject",
    "reason": "一句话说明价值判断理由"
  },
  "synthesis": {
    "tldr": "一句话结论，≤50字",
    "fact_summary": {
      "what": "发生了什么",
      "who": "关键角色",
      "when": "时间节点",
      "scale": "规模数据"
    },
    "action_guide": {
      "for_developers": ["行动1", "行动2"],
      "for_investors": ["关注点1"],
      "pitfalls": ["避坑点1"]
    },
    "logic_chain": [
      {
        "premise": "前提",
        "inference": "推断",
        "confidence": "high/medium/low",
        "source_ids": [1, 2]
      }
    ],
    "verdict": {
      "impact_level": "paradigm_shift/significant/incremental/noise",
      "time_sensitivity": "act_now/watch_closely/background",
      "analyst_note": "分析师点评，≤100字"
    }
  },
  "source_contributions": [
    {
      "source_id": 1,
      "contribution": "提供了XX关键信息",
      "cited_in": ["tldr", "fact_summary.what"]
    }
  ]
}
```

## 重要规则
1. 如果 value_assessment.level 是 "reject"，synthesis 字段可以为 null
2. source_contributions 必须列出每个被采用的来源及其贡献
3. logic_chain 中的 source_ids 必须指向支持该推断的来源
4. 优先采信高权重来源 (god > expert > insider > observer)
5. 不要输出 JSON 以外的任何内容"""


class EnhancedSynthesisEngine:
    """增强版情报合成引擎"""

    # 价值等级阈值
    MIN_SOURCES_FOR_HIGH = 3      # 高价值至少需要 3 个来源
    MIN_UNIQUE_KOLS_FOR_HIGH = 2  # 高价值至少需要 2 个不同 KOL

    def __init__(
        self,
        llm_client: AsyncOpenAI,
        model: str = "qwen-plus",
        temperature: float = 0.2,
        max_tokens: int = 2500,
        reject_low_value: bool = True,  # 是否拒绝低价值内容
    ):
        self.llm = llm_client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reject_low_value = reject_low_value

    async def synthesize(
        self,
        topic_title: str,
        sources: List[Dict[str, Any]],
        topic_id: Optional[int] = None,
    ) -> EnhancedSynthesisResult:
        """
        合成情报包

        Args:
            topic_title: 主题标题
            sources: 原始来源列表，每个来源必须包含 source_id
            topic_id: 主题 ID

        Returns:
            EnhancedSynthesisResult
        """
        if not sources:
            return EnhancedSynthesisResult(
                success=False,
                intel_id="",
                synthesis=None,
                source_count=0,
                kol_count=0,
                value_level=ValueLevel.REJECT,
                source_mappings=[],
                rejection_reason="没有可合成的来源"
            )

        # 预处理：计算权重、排序
        processed_sources = self._preprocess_sources(sources)

        # 统计
        intel_id = self._generate_intel_id(topic_title, topic_id)
        kol_handles = set(s.get("kol_handle") for s in sources if s.get("kol_handle"))
        kol_count = len(kol_handles)

        # 构建 XML 格式的 prompt
        prompt = self._build_xml_prompt(topic_title, processed_sources)

        try:
            response = await self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": ENHANCED_SYNTHESIS_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)

            # 解析价值评估
            value_assessment = result.get("value_assessment", {})
            value_level = self._parse_value_level(value_assessment.get("level", "medium"))

            # 检查是否拒绝
            if value_level == ValueLevel.REJECT:
                return EnhancedSynthesisResult(
                    success=False,
                    intel_id=intel_id,
                    synthesis=None,
                    source_count=len(sources),
                    kol_count=kol_count,
                    value_level=value_level,
                    source_mappings=[],
                    rejection_reason=value_assessment.get("reason", "内容价值过低")
                )

            # 如果配置了拒绝低价值，且价值为 LOW
            if self.reject_low_value and value_level == ValueLevel.LOW:
                return EnhancedSynthesisResult(
                    success=False,
                    intel_id=intel_id,
                    synthesis=None,
                    source_count=len(sources),
                    kol_count=kol_count,
                    value_level=value_level,
                    source_mappings=[],
                    rejection_reason=f"低价值内容: {value_assessment.get('reason', '')}"
                )

            # 解析合成结果
            synthesis = result.get("synthesis", {})
            synthesis = self._validate_synthesis(synthesis)

            # 解析来源映射
            source_mappings = self._parse_source_mappings(
                result.get("source_contributions", []),
                processed_sources
            )

            # 添加元数据
            synthesis["source_count"] = len(sources)
            synthesis["kol_count"] = kol_count
            synthesis["value_level"] = value_level.value

            logger.info(
                f"情报合成成功: {intel_id}, "
                f"价值={value_level.value}, 来源={len(sources)}"
            )

            return EnhancedSynthesisResult(
                success=True,
                intel_id=intel_id,
                synthesis=synthesis,
                source_count=len(sources),
                kol_count=kol_count,
                value_level=value_level,
                source_mappings=source_mappings
            )

        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}")
            return EnhancedSynthesisResult(
                success=False,
                intel_id=intel_id,
                synthesis=None,
                source_count=len(sources),
                kol_count=kol_count,
                value_level=ValueLevel.LOW,
                source_mappings=[],
                error=f"JSON 解析失败: {str(e)}"
            )
        except Exception as e:
            logger.error(f"合成失败: {e}")
            return EnhancedSynthesisResult(
                success=False,
                intel_id=intel_id,
                synthesis=None,
                source_count=len(sources),
                kol_count=kol_count,
                value_level=ValueLevel.LOW,
                source_mappings=[],
                error=str(e)
            )

    def _preprocess_sources(
        self,
        sources: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """预处理来源：计算权重、排序"""
        # KOL 等级权重
        tier_weights = {
            "god": 10.0,
            "expert": 5.0,
            "insider": 2.0,
            "observer": 1.0,
        }

        processed = []
        for source in sources:
            # 计算综合权重
            tier = source.get("kol_tier", "observer").lower()
            base_weight = tier_weights.get(tier, 1.0)

            # 互动数据加权
            metrics = source.get("metrics", {})
            engagement = (
                metrics.get("likes", 0) * 0.1 +
                metrics.get("retweets", 0) * 0.3 +
                metrics.get("replies", 0) * 0.2 +
                metrics.get("stars", 0) * 0.5
            )
            engagement_bonus = min(engagement / 100, 5.0)  # 最多加 5 分

            # 自定义权重
            custom_weight = source.get("kol_weight", 1.0)

            # 综合权重
            total_weight = base_weight * custom_weight + engagement_bonus

            source["_weight"] = round(total_weight, 2)
            processed.append(source)

        # 按权重降序排序
        processed.sort(key=lambda x: x["_weight"], reverse=True)

        return processed

    def _build_xml_prompt(
        self,
        topic_title: str,
        sources: List[Dict[str, Any]]
    ) -> str:
        """构建 XML 格式的 prompt"""
        xml_sources = []

        for source in sources:
            source_id = source.get("source_id", 0)
            kol_handle = source.get("kol_handle", "unknown")
            kol_tier = source.get("kol_tier", "observer")
            weight = source.get("_weight", 1.0)
            text = source.get("text", "")[:1000]  # 限制长度
            published_at = source.get("published_at", "")

            # 转义 XML 特殊字符
            text = self._escape_xml(text)

            xml_source = f"""<source id="{source_id}">
  <kol handle="{kol_handle}" tier="{kol_tier}" weight="{weight}"/>
  <published_at>{published_at}</published_at>
  <content><![CDATA[{text}]]></content>
</source>"""
            xml_sources.append(xml_source)

        return f"""<synthesis_request>
  <topic>{self._escape_xml(topic_title)}</topic>
  <source_count>{len(sources)}</source_count>
  <sources>
{chr(10).join(xml_sources)}
  </sources>
</synthesis_request>

请分析以上 {len(sources)} 条来源，评估价值并合成情报包。
注意：source_id 用于追溯，请在 source_contributions 中标注每个来源的贡献。"""

    def _escape_xml(self, text: str) -> str:
        """转义 XML 特殊字符"""
        return (
            text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    def _parse_value_level(self, level_str: str) -> ValueLevel:
        """解析价值等级"""
        level_map = {
            "high": ValueLevel.HIGH,
            "medium": ValueLevel.MEDIUM,
            "low": ValueLevel.LOW,
            "reject": ValueLevel.REJECT,
        }
        return level_map.get(level_str.lower(), ValueLevel.MEDIUM)

    def _validate_synthesis(self, synthesis: Dict[str, Any]) -> Dict[str, Any]:
        """验证并修复合成结果"""
        if not synthesis:
            return self._get_default_synthesis()

        # 确保必填字段
        if not synthesis.get("tldr"):
            synthesis["tldr"] = "情报合成中"

        if not synthesis.get("fact_summary"):
            synthesis["fact_summary"] = {
                "what": "待补充",
                "who": "待补充",
                "when": "待补充",
                "scale": "待补充"
            }

        if not synthesis.get("action_guide"):
            synthesis["action_guide"] = {
                "for_developers": [],
                "for_investors": [],
                "pitfalls": []
            }

        if not synthesis.get("logic_chain"):
            synthesis["logic_chain"] = []

        if not synthesis.get("verdict"):
            synthesis["verdict"] = {
                "impact_level": "incremental",
                "time_sensitivity": "background",
                "analyst_note": "待分析"
            }

        return synthesis

    def _get_default_synthesis(self) -> Dict[str, Any]:
        """获取默认合成结构"""
        return {
            "tldr": "情报合成中",
            "fact_summary": {
                "what": "待补充",
                "who": "待补充",
                "when": "待补充",
                "scale": "待补充"
            },
            "action_guide": {
                "for_developers": [],
                "for_investors": [],
                "pitfalls": []
            },
            "logic_chain": [],
            "verdict": {
                "impact_level": "incremental",
                "time_sensitivity": "background",
                "analyst_note": "待分析"
            }
        }

    def _parse_source_mappings(
        self,
        contributions: List[Dict[str, Any]],
        sources: List[Dict[str, Any]]
    ) -> List[SourceMapping]:
        """解析来源映射"""
        # 构建 source_id 到 source 的映射
        source_map = {s.get("source_id"): s for s in sources}

        mappings = []
        for contrib in contributions:
            source_id = contrib.get("source_id")
            if source_id is None:
                continue

            source = source_map.get(source_id, {})

            mapping = SourceMapping(
                source_id=source_id,
                kol_handle=source.get("kol_handle", ""),
                kol_tier=source.get("kol_tier", "observer"),
                weight=source.get("_weight", 1.0),
                contribution=contrib.get("contribution", ""),
                cited_in=contrib.get("cited_in", [])
            )
            mappings.append(mapping)

        return mappings

    def _generate_intel_id(
        self,
        topic_title: str,
        topic_id: Optional[int] = None
    ) -> str:
        """生成情报包 ID"""
        date_str = datetime.now().strftime("%Y%m%d")
        slug = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', topic_title)[:20]
        slug = slug.lower() or "intel"

        if topic_id:
            return f"intel_{date_str}_{topic_id}_{slug}"
        return f"intel_{date_str}_{slug}"


async def enhanced_synthesize_topic(
    engine: EnhancedSynthesisEngine,
    topic_id: int,
    topic_title: str,
    raw_contents: List[Any],
    kol_map: Optional[Dict[int, Any]] = None
) -> EnhancedSynthesisResult:
    """
    便捷函数：使用增强引擎合成主题情报

    Args:
        engine: 增强合成引擎
        topic_id: 主题 ID
        topic_title: 主题标题
        raw_contents: RawContent 对象列表
        kol_map: KOL ID 到 KOL 对象的映射

    Returns:
        EnhancedSynthesisResult
    """
    kol_map = kol_map or {}

    sources = []
    for content in raw_contents:
        kol = kol_map.get(content.kol_id) if content.kol_id else None

        source = {
            "source_id": content.id,  # 关键：包含原始内容 ID
            "text": content.text_content,
            "source_type": content.source_type.value if hasattr(content.source_type, 'value') else str(content.source_type),
            "kol_name": kol.name if kol else "未知",
            "kol_handle": kol.handle if kol else "",
            "kol_tier": kol.tier.value if kol and hasattr(kol.tier, 'value') else "observer",
            "kol_weight": kol.weight if kol else 1.0,
            "published_at": content.published_at.isoformat() if content.published_at else "",
            "metrics": {
                "likes": content.likes or 0,
                "retweets": content.retweets or 0,
                "replies": content.replies or 0,
                "stars": content.stars or 0
            }
        }
        sources.append(source)

    return await engine.synthesize(topic_title, sources, topic_id)
