"""数据源配置加载器 - 支持 RSSHub 和传统 RSS"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import yaml

from src.logger import get_logger

logger = get_logger(__name__)


class SourceType(Enum):
    """数据源类型"""
    RSS = "rss"           # 传统 RSS
    X_KOL = "x_kol"       # X/Twitter KOL
    X_KEYWORD = "x_keyword"  # X 关键词搜索
    GITHUB = "github"     # GitHub
    PAPER = "paper"       # 论文


@dataclass
class AInsightSource:
    """AInsight 数据源"""
    name: str
    url: str                          # 完整 URL
    source_type: SourceType
    enabled: bool = True
    category: str = "news"            # 分类
    tags: List[str] = field(default_factory=list)

    # KOL 相关
    kol_handle: Optional[str] = None
    kol_tier: Optional[str] = None    # god/expert/insider/observer
    platform: str = "x"

    # 元数据
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceConfig:
    """源配置"""
    sources: List[AInsightSource]
    rsshub_base_url: str
    settings: Dict[str, Any]


def load_sources(config_path: str = "config/sources.yaml") -> SourceConfig:
    """
    加载数据源配置

    Returns:
        SourceConfig 包含所有源和设置
    """
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    sources = []

    # RSSHub 配置
    rsshub_config = config.get("rsshub", {})
    rsshub_base_url = rsshub_config.get("base_url", "https://rsshub.app")

    settings = config.get("settings", {})

    # 加载 AI KOL
    for kol in config.get("ai_kols", []):
        if not kol.get("enabled", True):
            continue

        route = kol.get("rsshub_route", "")
        url = f"{rsshub_base_url}{route}" if route else ""

        sources.append(AInsightSource(
            name=kol.get("name", kol.get("handle", "Unknown")),
            url=url,
            source_type=SourceType.X_KOL,
            enabled=True,
            category="kol",
            tags=kol.get("tags", []),
            kol_handle=kol.get("handle"),
            kol_tier=kol.get("tier", "observer"),
            platform=kol.get("platform", "x"),
        ))

    # 加载 AI 关键词
    for kw in config.get("ai_keywords", []):
        if not kw.get("enabled", True):
            continue

        route = kw.get("rsshub_route", "")
        url = f"{rsshub_base_url}{route}" if route else ""

        sources.append(AInsightSource(
            name=f"X搜索: {kw.get('keyword', '')}",
            url=url,
            source_type=SourceType.X_KEYWORD,
            enabled=True,
            category=kw.get("category", "news"),
            tags=[kw.get("keyword", "")],
        ))

    # 加载 GitHub
    for gh in config.get("github", []):
        if not gh.get("enabled", True):
            continue

        route = gh.get("rsshub_route", "")
        url = f"{rsshub_base_url}{route}" if route else ""

        sources.append(AInsightSource(
            name=gh.get("name", "GitHub"),
            url=url,
            source_type=SourceType.GITHUB,
            enabled=True,
            category=gh.get("category", "research"),
            tags=["github"],
        ))

    # 加载科技媒体
    for media in config.get("tech_media", []):
        if not media.get("enabled", True):
            continue

        # 支持直接 URL 或 RSSHub 路由
        if media.get("url"):
            url = media["url"]
        elif media.get("rsshub_route"):
            url = f"{rsshub_base_url}{media['rsshub_route']}"
        else:
            continue

        sources.append(AInsightSource(
            name=media.get("name", "Unknown"),
            url=url,
            source_type=SourceType.RSS,
            enabled=True,
            category=media.get("category", "news"),
            tags=["media"],
        ))

    # 加载论文
    for paper in config.get("papers", []):
        if not paper.get("enabled", True):
            continue

        route = paper.get("rsshub_route", "")
        url = f"{rsshub_base_url}{route}" if route else ""

        sources.append(AInsightSource(
            name=paper.get("name", "Paper"),
            url=url,
            source_type=SourceType.PAPER,
            enabled=True,
            category=paper.get("category", "research"),
            tags=["paper", "research"],
        ))

    # 加载传统新闻源（china/world）
    for region_key in ["china", "world"]:
        for item in config.get(region_key, []):
            if not item.get("enabled", True):
                continue

            sources.append(AInsightSource(
                name=item.get("name", "Unknown"),
                url=item.get("url", ""),
                source_type=SourceType.RSS,
                enabled=True,
                category="news",
                tags=[region_key],
            ))

    logger.info(f"加载 {len(sources)} 个数据源")

    # 按类型统计
    type_counts = {}
    for s in sources:
        type_counts[s.source_type.value] = type_counts.get(s.source_type.value, 0) + 1

    for t, c in type_counts.items():
        logger.debug(f"  - {t}: {c} 个")

    return SourceConfig(
        sources=sources,
        rsshub_base_url=rsshub_base_url,
        settings=settings,
    )


def get_enabled_sources(config: SourceConfig) -> List[AInsightSource]:
    """获取启用的数据源"""
    return [s for s in config.sources if s.enabled]


def get_sources_by_type(
    config: SourceConfig,
    source_type: SourceType
) -> List[AInsightSource]:
    """按类型获取数据源"""
    return [s for s in config.sources if s.source_type == source_type and s.enabled]
