"""
情报合成引擎 - 将多条原始内容合成为高密度情报包

功能：
1. 从主题下的原始内容提取关键信息
2. 使用 LLM 合成结构化情报
3. 生成 TLDR、事实摘要、行动指南、逻辑推演链等
"""
import json
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from openai import AsyncOpenAI

from src.logger import get_logger

logger = get_logger(__name__)


# 情报合成 System Prompt
SYNTHESIS_SYSTEM_PROMPT = """你是 AInsight Pro 的首席情报分析师，专门为 AI 从业者（开发者、投资人、创业者）提供高密度、可执行的技术情报。

## 你的身份
- 前 a16z 合伙人级别的技术分析师
- 深度理解 AI 技术栈（从 Transformer 到 Agent 到具身智能）
- 擅长从噪音中提取信号，从信号中推导行动

## 你的任务
将多条关于同一主题的原始信息（X 推文、GitHub 动态、新闻）合成为一份结构化情报包。

## 输出要求

### 必须遵守的原则
1. **拒绝废话**：每句话都要有信息增量，删除所有"据悉"、"值得关注"等水词
2. **量化优先**：能用数字说话就不用形容词（"增长 300%" 而非 "大幅增长"）
3. **立场鲜明**：必须给出明确判断，不允许"有待观察"式的骑墙结论
4. **��执行**：行动指南必须具体到"打开 XX 网站，执行 XX 操作"
5. **证据链闭环**：每个推断必须能追溯到具体的原始来源

### 输出 JSON 结构
严格按照以下结构输出，不要添加任何额外字段：

```json
{
  "tldr": "一句话结论，≤50字，必须包含核心判断",
  "fact_summary": {
    "what": "发生了什么（一句话）",
    "who": "关键角色（人名/公司名）",
    "when": "时间节点",
    "scale": "规模数据（如有）"
  },
  "action_guide": {
    "for_developers": ["具体行动1", "具体行动2"],
    "for_investors": ["关注点1", "关注点2"],
    "pitfalls": ["避坑点1", "避坑点2"]
  },
  "logic_chain": [
    {
      "premise": "前提（来自原始信息）",
      "inference": "推断",
      "confidence": "high/medium/low"
    }
  ],
  "historical_context": [
    {
      "event": "历史事件名称",
      "date": "YYYY-MM-DD",
      "relevance": "与当前事件的关联"
    }
  ],
  "verdict": {
    "impact_level": "paradigm_shift/significant/incremental/noise",
    "time_sensitivity": "act_now/watch_closely/background",
    "analyst_note": "分析师点评，≤100字，必须有态度"
  }
}
```

### impact_level 判断标准
- **paradigm_shift**：改变行业格局（如 ChatGPT 发布、Transformer 论文）
- **significant**：重要进展，值得深入研究（如主流框架大版本更新）
- **incremental**：渐进式改进（如小版本更新、性能优化）
- **noise**：营销噪音或重复信息

### time_sensitivity 判断标准
- **act_now**：24小时内需要行动（如限时 API、安全漏洞）
- **watch_closely**：本周内需要关注（如重要发布、融资消息）
- **background**：作为背景知识储备

## 禁止事项
1. 不要输出 JSON 以外的任何内容
2. 不要使用"可能"、"或许"、"据说"等模糊词汇
3. 不要复述原文，必须提炼和升华
4. 不要遗漏任何必填字段
5. 不要在 analyst_note 中使用"值得关注"、"拭目以待"等废话"""


@dataclass
class SynthesisResult:
    """合成结果"""
    success: bool
    intel_id: str
    synthesis: Optional[Dict[str, Any]]
    source_count: int
    kol_count: int
    error: Optional[str] = None


class SynthesisEngine:
    """情报合成引擎"""

    def __init__(
        self,
        llm_client: AsyncOpenAI,
        model: str = "qwen-plus",
        temperature: float = 0.3,
        max_tokens: int = 2000
    ):
        """
        初始化合成引擎

        Args:
            llm_client: OpenAI 兼容的异步客户端
            model: 使用的模型名称
            temperature: 生成温度（越低越稳定）
            max_tokens: 最大输出 token 数
        """
        self.llm = llm_client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def synthesize(
        self,
        topic_title: str,
        sources: List[Dict[str, Any]],
        topic_id: Optional[int] = None
    ) -> SynthesisResult:
        """
        合成情报包

        Args:
            topic_title: 主题标题
            sources: 原始来源列表，每个来源包含：
                - text: 文本内容
                - source_type: 来源类型
                - kol_name: KOL 名称
                - kol_handle: KOL handle
                - kol_tier: KOL 等级
                - published_at: 发布时间
                - metrics: 互动数据 {likes, retweets, replies, stars}
            topic_id: 主题 ID（用于生成 intel_id）

        Returns:
            SynthesisResult 合成结果
        """
        if not sources:
            return SynthesisResult(
                success=False,
                intel_id="",
                synthesis=None,
                source_count=0,
                kol_count=0,
                error="没有可合成的来源"
            )

        # 生成 intel_id
        intel_id = self._generate_intel_id(topic_title, topic_id)

        # 统计 KOL 数量
        kol_handles = set(s.get("kol_handle") for s in sources if s.get("kol_handle"))
        kol_count = len(kol_handles)

        # 构建合成 prompt
        prompt = self._build_synthesis_prompt(topic_title, sources)

        try:
            response = await self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"}
            )

            synthesis = json.loads(response.choices[0].message.content)

            # 验证必填字段
            synthesis = self._validate_and_fix(synthesis)

            # 添加元数据
            synthesis["source_count"] = len(sources)
            synthesis["kol_count"] = kol_count

            logger.info(f"情报合成成功: {intel_id}, {len(sources)} 条来源")

            return SynthesisResult(
                success=True,
                intel_id=intel_id,
                synthesis=synthesis,
                source_count=len(sources),
                kol_count=kol_count
            )

        except json.JSONDecodeError as e:
            logger.error(f"LLM 返回非 JSON 格式: {e}")
            return SynthesisResult(
                success=False,
                intel_id=intel_id,
                synthesis=None,
                source_count=len(sources),
                kol_count=kol_count,
                error=f"JSON 解析失败: {str(e)}"
            )
        except Exception as e:
            logger.error(f"情报合成失败: {e}")
            return SynthesisResult(
                success=False,
                intel_id=intel_id,
                synthesis=None,
                source_count=len(sources),
                kol_count=kol_count,
                error=str(e)
            )

    def _build_synthesis_prompt(
        self,
        topic_title: str,
        sources: List[Dict[str, Any]]
    ) -> str:
        """构建合成 prompt"""
        sources_text = []

        for i, source in enumerate(sources, 1):
            # 提取来源信息
            source_type = source.get("source_type", "unknown")
            kol_name = source.get("kol_name", "未知")
            kol_handle = source.get("kol_handle", "")
            kol_tier = source.get("kol_tier", "observer")
            published_at = source.get("published_at", "未知时间")
            text = source.get("text", "")[:800]  # 限制长度

            # 提取互动数据
            metrics = source.get("metrics", {})
            likes = metrics.get("likes", 0)
            retweets = metrics.get("retweets", 0)
            stars = metrics.get("stars", 0)

            # 构建来源文本
            metrics_str = ""
            if likes or retweets:
                metrics_str = f"❤️ {likes} 🔄 {retweets}"
            if stars:
                metrics_str += f" ⭐ {stars}"

            source_text = f"""### 来源 {i}: {source_type} - {kol_name} (@{kol_handle}) [{kol_tier}]
发布时间: {published_at}
互动数据: {metrics_str or '无'}
内容:
\"\"\"
{text}
\"\"\""""
            sources_text.append(source_text)

        return f"""## 任务
将以下 {len(sources)} 条关于【{topic_title}】的原始信息合成为情报包。

## 原始信息

{chr(10).join(sources_text)}

## 合成要求
1. 去除重复信息，提取共识和分歧
2. 识别最有价值的独家观点
3. 推断未明说但可合理推导的结论
4. 关联历史事件，提供纵向视角
5. 优先采信高等级 KOL (god > expert > insider > observer) 的观点

## 输出
请严格按照 System Prompt 中定义的 JSON 结构输出。"""

    def _validate_and_fix(self, synthesis: Dict[str, Any]) -> Dict[str, Any]:
        """验证并修复合成结果"""
        # 确保必填字段存在
        if not synthesis.get("tldr"):
            synthesis["tldr"] = "情报合成中，请稍后查看详情"

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

        if not synthesis.get("historical_context"):
            synthesis["historical_context"] = []

        if not synthesis.get("verdict"):
            synthesis["verdict"] = {
                "impact_level": "incremental",
                "time_sensitivity": "background",
                "analyst_note": "待分析"
            }

        # 验证 verdict 字段
        verdict = synthesis["verdict"]
        valid_impact = ["paradigm_shift", "significant", "incremental", "noise"]
        valid_sensitivity = ["act_now", "watch_closely", "background"]

        if verdict.get("impact_level") not in valid_impact:
            verdict["impact_level"] = "incremental"
        if verdict.get("time_sensitivity") not in valid_sensitivity:
            verdict["time_sensitivity"] = "background"

        return synthesis

    def _generate_intel_id(
        self,
        topic_title: str,
        topic_id: Optional[int] = None
    ) -> str:
        """生成情报包 ID"""
        date_str = datetime.now().strftime("%Y%m%d")

        # 从标题提取关键词作为 slug
        slug = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', topic_title)[:20]
        slug = slug.lower().replace(' ', '-') or "intel"

        if topic_id:
            return f"intel_{date_str}_{topic_id}_{slug}"
        return f"intel_{date_str}_{slug}"


async def synthesize_topic(
    engine: SynthesisEngine,
    topic_id: int,
    topic_title: str,
    raw_contents: List[Any],
    kol_map: Optional[Dict[int, Any]] = None
) -> SynthesisResult:
    """
    便捷函数：合成主题的情报包

    Args:
        engine: 合成引擎
        topic_id: 主题 ID
        topic_title: 主题标题
        raw_contents: RawContent 对象列表
        kol_map: KOL ID 到 KOL 对象的映射

    Returns:
        SynthesisResult
    """
    kol_map = kol_map or {}

    # 转换为合成引擎需要的格式
    sources = []
    for content in raw_contents:
        kol = kol_map.get(content.kol_id) if content.kol_id else None

        source = {
            "text": content.text_content,
            "source_type": content.source_type.value if hasattr(content.source_type, 'value') else str(content.source_type),
            "kol_name": kol.name if kol else "未知",
            "kol_handle": kol.handle if kol else "",
            "kol_tier": kol.tier.value if kol and hasattr(kol.tier, 'value') else "observer",
            "published_at": content.published_at.isoformat() if content.published_at else "未知",
            "metrics": {
                "likes": content.likes or 0,
                "retweets": content.retweets or 0,
                "replies": content.replies or 0,
                "stars": content.stars or 0
            }
        }
        sources.append(source)

    return await engine.synthesize(topic_title, sources, topic_id)
