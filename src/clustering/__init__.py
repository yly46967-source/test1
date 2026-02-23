"""主题聚类模块"""
# 新版简化流水线
from .pipeline import SimplePipeline, ClusterDecision, ClusterResult
from .content_filter import ContentFilter, FilterResult, filter_contents

# 兼容旧版导入
from .topic_cluster import TopicClusterer, ClusterAction
from .deduplicator import SimHash, ContentDeduplicator
from .enhanced_pipeline import EnhancedClusteringPipeline

__all__ = [
    # 新版
    "SimplePipeline",
    "ClusterDecision",
    "ClusterResult",
    "ContentFilter",
    "FilterResult",
    "filter_contents",
    # 兼容旧版
    "TopicClusterer",
    "ClusterAction",
    "SimHash",
    "ContentDeduplicator",
    "EnhancedClusteringPipeline",
]
