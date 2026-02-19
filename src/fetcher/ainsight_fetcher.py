"""AInsight 统一抓取器 - 支持 RSSHub 和传统 RSS"""
import asyncio
import hashlib
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from html import unescape

import feedparser
import httpx
import trafilatura

from src.logger import get_logger
from .source_loader import AInsightSource, SourceType

logger = get_logger(__name__)


@dataclass
class RawContentItem:
    """原始内容项 - 用于聚类流水线"""
    text: str                           # 文本内容
    source_type: str                    # 来源类型
    source_url: str                     # 原始链接
    title: Optional[str] = None         # 标题
    published_at: Optional[datetime] = None
    kol_id: Optional[int] = None        # KOL ID（数据库）
    kol_name: Optional[str] = None      # KOL 名称
    kol_handle: Optional[str] = None    # KOL handle
    kol_tier: Optional[str] = None      # KOL 等级
    metrics: Dict[str, int] = field(default_factory=dict)  # 互动数据
    media_urls: List[str] = field(default_factory=list)    # 媒体链接
    raw_data: Optional[Dict] = None     # 原始数据


class AInsightFetcher:
    """AInsight 统一抓取器"""

    RETRYABLE_EXCEPTIONS = (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.ConnectTimeout,
    )

    def __init__(
        self,
        max_items: int = 10,
        timeout: int = 30,
        max_retries: int = 3,
        user_agent: str = "AInsight/1.0 (RSS Reader)",
    ):
        self.max_items = max_items
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent

    async def fetch_source(self, source: AInsightSource) -> List[RawContentItem]:
        """
        抓取单个数据源

        Args:
            source: 数据源配置

        Returns:
            原始内容列表
        """
        if not source.url:
            logger.warning(f"[{source.name}] URL 为空，跳过")
            return []

        try:
            content = await self._fetch_with_retry(source.url, source.name)
            if content is None:
                return []

            # 解析 RSS
            feed = feedparser.parse(content)
            if not feed.entries:
                logger.warning(f"[{source.name}] 无条目")
                return []

            logger.debug(f"[{source.name}] 解析到 {len(feed.entries)} 条")

            # 根据源类型解析
            items = []
            for entry in feed.entries[:self.max_items]:
                item = self._parse_entry(entry, source)
                if item:
                    items.append(item)

            return items

        except Exception as e:
            logger.error(f"[{source.name}] 抓取失败: {e}")
            return []

    async def fetch_all(
        self,
        sources: List[AInsightSource],
        concurrency: int = 5,
    ) -> Tuple[List[RawContentItem], Dict[str, int]]:
        """
        并发抓取所有数据源

        Returns:
            (所有内容列表, 统计信息)
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch_with_semaphore(source: AInsightSource):
            async with semaphore:
                return source.name, await self.fetch_source(source)

        tasks = [fetch_with_semaphore(s) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items = []
        stats = {"success": 0, "failed": 0, "total_items": 0}

        for result in results:
            if isinstance(result, Exception):
                stats["failed"] += 1
                logger.error(f"抓取异常: {result}")
            else:
                name, items = result
                if items:
                    all_items.extend(items)
                    stats["success"] += 1
                    stats["total_items"] += len(items)
                    logger.info(f"[{name}] 抓取 {len(items)} 条")
                else:
                    stats["failed"] += 1

        return all_items, stats

    async def _fetch_with_retry(self, url: str, name: str) -> Optional[str]:
        """带重试的 HTTP 请求"""
        last_exception = None
        delay = 1.0

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(
                        url,
                        headers={"User-Agent": self.user_agent},
                        follow_redirects=True,
                    )
                    response.raise_for_status()
                    return response.text

            except self.RETRYABLE_EXCEPTIONS as e:
                last_exception = e
                if attempt < self.max_retries:
                    logger.warning(
                        f"[{name}] 请求失败，重试 {attempt + 1}/{self.max_retries}"
                    )
                    await asyncio.sleep(delay)
                    delay *= 2

            except httpx.HTTPStatusError as e:
                logger.warning(f"[{name}] HTTP {e.response.status_code}")
                return None

        logger.error(f"[{name}] 重试 {self.max_retries} 次后失败")
        return None

    def _parse_entry(
        self,
        entry: Any,
        source: AInsightSource
    ) -> Optional[RawContentItem]:
        """解析 RSS 条目"""
        try:
            # 基础字段
            title = entry.get("title", "")
            link = entry.get("link", "")

            if not link:
                return None

            # 发布时间
            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published_at = datetime(*entry.published_parsed[:6])

            # 内容 - 优先使用完整内容
            content = ""

            # 1. 尝试 content 字段（通常是完整内容）
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            # 2. 尝试 content_encoded（RSS 2.0 扩展）
            elif hasattr(entry, "content_encoded"):
                content = entry.content_encoded
            # 3. 尝试 description（可能包含更多内容）
            elif hasattr(entry, "description"):
                content = entry.description
            # 4. 最后使用 summary
            elif hasattr(entry, "summary"):
                content = entry.summary

            # 清理 HTML
            text = self._clean_html(content)
            if title:
                text = f"{title}\n\n{text}"

            # 如果内容太短（<500字符），尝试抓取完整内容和图片
            MIN_CONTENT_LENGTH = 500
            full_page_html = None
            if len(text) < MIN_CONTENT_LENGTH and link:
                logger.debug(f"内容太短 ({len(text)} chars)，尝试抓取完整内容: {link}")
                full_text, full_page_html = self._fetch_full_content_sync(link, source.name)
                if full_text and len(full_text) > len(text):
                    text = f"{title}\n\n{full_text}" if title else full_text
                    logger.info(f"[{source.name}] 抓取完整内容成功: {len(full_text)} chars")

            # 提取媒体链接（优先从完整页面提取）
            media_urls = self._extract_media(entry, full_page_html, link)

            # 提取互动数据（RSSHub 可能包含）
            metrics = self._extract_metrics(entry, content)

            # 构建原始内容项
            item = RawContentItem(
                text=text,
                source_type=source.source_type.value,
                source_url=link,
                title=title,
                published_at=published_at,
                kol_name=source.name if source.source_type == SourceType.X_KOL else None,
                kol_handle=source.kol_handle,
                kol_tier=source.kol_tier,
                metrics=metrics,
                media_urls=media_urls,
                raw_data={
                    "source_name": source.name,
                    "category": source.category,
                    "tags": source.tags,
                },
            )

            return item

        except Exception as e:
            logger.warning(f"解析条目失败: {e}")
            return None

    def _clean_html(self, html: str) -> str:
        """清理 HTML 标签，保留段落结构"""
        if not html:
            return ""

        # 将块级元素转换为换行
        html = re.sub(r'</(p|div|br|h[1-6]|li|tr)>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)

        # 移除所有 HTML 标签
        text = re.sub(r'<[^>]+>', '', html)

        # 解码 HTML 实体
        text = unescape(text)

        # 清理多余空白，但保留换行
        lines = text.split('\n')
        lines = [re.sub(r'\s+', ' ', line).strip() for line in lines]
        lines = [line for line in lines if line]  # 移除空行

        return '\n\n'.join(lines)

    def _fetch_full_content_sync(self, url: str, source_name: str) -> tuple[Optional[str], Optional[str]]:
        """使用 trafilatura 抓取完整网页内容（同步版本，输出 Markdown）

        Returns:
            (extracted_text, html_content)
        """
        try:
            import requests

            response = requests.get(
                url,
                headers={"User-Agent": self.user_agent},
                timeout=15.0,
                allow_redirects=True,
            )
            response.raise_for_status()

            html_content = response.text

            # 使用 trafilatura 提取正文，输出为 Markdown 格式
            extracted = trafilatura.extract(
                html_content,
                include_comments=False,
                include_tables=True,
                include_images=True,
                no_fallback=False,
                output_format='markdown',  # 输出 Markdown 格式
                with_metadata=False,
            )

            return (extracted if extracted else None, html_content)

        except Exception as e:
            logger.warning(f"[{source_name}] 抓取完整内容失败: {e}")
            return (None, None)

    def _extract_media(self, entry: Any, full_page_html: Optional[str] = None, page_url: Optional[str] = None) -> List[str]:
        """提取媒体链接，优先从完整页面提取主图"""
        media_urls = []

        # 1. 如果有完整页面 HTML，提取主图
        if full_page_html:
            from urllib.parse import urljoin
            from lxml import html as lxml_html

            try:
                tree = lxml_html.fromstring(full_page_html)

                # 提取 og:image (Open Graph)
                og_image = tree.xpath('//meta[@property="og:image"]/@content')
                if og_image:
                    media_urls.extend(og_image[:1])  # 只取第一个

                # 提取 twitter:image
                twitter_image = tree.xpath('//meta[@name="twitter:image"]/@content')
                if twitter_image and twitter_image[0] not in media_urls:
                    media_urls.extend(twitter_image[:1])

                # 提取文章主图 (article 标签内的第一张图)
                article_imgs = tree.xpath('//article//img/@src | //article//img/@data-src')
                for img in article_imgs[:3]:
                    if page_url:
                        img = urljoin(page_url, img)
                    if img not in media_urls and img.startswith('http'):
                        media_urls.append(img)

                # 提取所有大尺寸图片 (宽度 > 400px)
                large_imgs = tree.xpath('//img[@width>400]/@src | //img[contains(@class, "featured")]/@src')
                for img in large_imgs[:2]:
                    if page_url:
                        img = urljoin(page_url, img)
                    if img not in media_urls and img.startswith('http'):
                        media_urls.append(img)

            except Exception as e:
                logger.debug(f"从完整页面提取图片失败: {e}")

        # 2. 从 RSS entry 提取
        # 检查 enclosures
        if hasattr(entry, "enclosures"):
            for enc in entry.enclosures:
                if enc.get("href") and enc["href"] not in media_urls:
                    media_urls.append(enc["href"])

        # 检查 media_content
        if hasattr(entry, "media_content"):
            for media in entry.media_content:
                if media.get("url") and media["url"] not in media_urls:
                    media_urls.append(media["url"])

        # 从内容中提取图片
        content = entry.get("summary", "") or entry.get("description", "")
        img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', content)
        for img in img_urls:
            if img not in media_urls:
                media_urls.append(img)

        return media_urls[:5]  # 最多 5 个

    def _extract_metrics(self, entry: Any, content: str) -> Dict[str, int]:
        """提取互动数据"""
        metrics = {}

        # RSSHub Twitter 格式可能包含互动数据
        # 尝试从内容中提取
        patterns = {
            "likes": r'(\d+)\s*(?:likes?|❤️|♥)',
            "retweets": r'(\d+)\s*(?:retweets?|🔁|RT)',
            "replies": r'(\d+)\s*(?:replies?|💬|comments?)',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                try:
                    metrics[key] = int(match.group(1))
                except ValueError:
                    pass

        return metrics


async def fetch_ainsight_sources(
    sources: List[AInsightSource],
    settings: Dict[str, Any],
) -> Tuple[List[RawContentItem], Dict[str, int]]:
    """
    便捷函数：抓取所有 AInsight 数据源

    Args:
        sources: 数据源列表
        settings: 配置

    Returns:
        (内容列表, 统计信息)
    """
    fetcher = AInsightFetcher(
        max_items=settings.get("max_items_per_source", 10),
        timeout=settings.get("request_timeout", 30),
        user_agent=settings.get("user_agent", "AInsight/1.0"),
    )

    concurrency = settings.get("concurrent_limit", 5)
    return await fetcher.fetch_all(sources, concurrency=concurrency)
