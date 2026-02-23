"""情报处理模块"""
# 新版简化合成
from .synthesis import SynthesisEngine, SynthesisResult, ValueLevel, synthesize_topic

# 兼容旧版
from .enhanced_synthesis import (
    EnhancedSynthesisEngine,
    EnhancedSynthesisResult,
    SourceMapping,
    enhanced_synthesize_topic,
    BatchSynthesizer,
    BatchSynthesisResult,
    batch_synthesize_topics,
)

__all__ = [
    # 新版
    "SynthesisEngine",
    "SynthesisResult",
    "ValueLevel",
    "synthesize_topic",
    # 兼容旧版
    "EnhancedSynthesisEngine",
    "EnhancedSynthesisResult",
    "SourceMapping",
    "enhanced_synthesize_topic",
    "BatchSynthesizer",
    "BatchSynthesisResult",
    "batch_synthesize_topics",
]
