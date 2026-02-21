"""数据抓取模块"""
from .source_loader import (
    load_sources as load_ainsight_sources,
    AInsightSource,
    SourceConfig,
    SourceType,
    get_enabled_sources,
    get_sources_by_type,
)
from .ainsight_fetcher import (
    AInsightFetcher,
    RawContentItem,
    fetch_ainsight_sources,
)
from .nitter_gateway import (
    NitterGateway,
    NitterInstance,
    InstanceStatus,
    get_nitter_gateway,
    reset_nitter_gateway,
)
from .twitter_fetcher import (
    TwitterFetcher,
    TwitterContent,
    fetch_twitter_kols,
)
from .fxtwitter_fetcher import (
    FxTwitterFetcher,
    FxTweetContent,
    fetch_tweet,
    fetch_tweets_batch,
)
from .playwright_twitter import (
    PlaywrightTwitterFetcher,
    TwitterPost,
    FetchResult,
    fetch_twitter_with_playwright,
    convert_to_raw_content,
    filter_today_tweets,
)

__all__ = [
    # AInsight
    "load_ainsight_sources",
    "AInsightSource",
    "SourceConfig",
    "SourceType",
    "get_enabled_sources",
    "get_sources_by_type",
    "AInsightFetcher",
    "RawContentItem",
    "fetch_ainsight_sources",
    # Nitter Gateway
    "NitterGateway",
    "NitterInstance",
    "InstanceStatus",
    "get_nitter_gateway",
    "reset_nitter_gateway",
    # Twitter Fetcher
    "TwitterFetcher",
    "TwitterContent",
    "fetch_twitter_kols",
    # FxTwitter Fetcher
    "FxTwitterFetcher",
    "FxTweetContent",
    "fetch_tweet",
    "fetch_tweets_batch",
    # Playwright Twitter (推荐)
    "PlaywrightTwitterFetcher",
    "TwitterPost",
    "FetchResult",
    "fetch_twitter_with_playwright",
    "convert_to_raw_content",
    "filter_today_tweets",
]
