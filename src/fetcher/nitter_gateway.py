"""Nitter 动态网关 - 多实例轮询与自动切换"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from enum import Enum

import httpx

from src.logger import get_logger

logger = get_logger(__name__)


class InstanceStatus(Enum):
    """实例状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"  # 响应慢但可用
    UNHEALTHY = "unhealthy"  # 不可用
    RATE_LIMITED = "rate_limited"  # 被限流


@dataclass
class NitterInstance:
    """Nitter 实例"""
    url: str
    status: InstanceStatus = InstanceStatus.HEALTHY
    last_check: float = 0
    success_count: int = 0
    fail_count: int = 0
    avg_latency_ms: float = 0
    consecutive_failures: int = 0
    rate_limit_until: float = 0  # 限流解除时间

    @property
    def is_available(self) -> bool:
        """是否可用"""
        if self.status == InstanceStatus.RATE_LIMITED:
            return time.time() > self.rate_limit_until
        return self.status in (InstanceStatus.HEALTHY, InstanceStatus.DEGRADED)

    @property
    def score(self) -> float:
        """计算实例评分（用于选择）"""
        if not self.is_available:
            return -1

        # 基础分 100
        score = 100.0

        # 成功率加分
        total = self.success_count + self.fail_count
        if total > 0:
            success_rate = self.success_count / total
            score += success_rate * 50

        # 延迟扣分
        if self.avg_latency_ms > 0:
            score -= min(self.avg_latency_ms / 100, 30)  # 最多扣 30 分

        # 连续失败扣分
        score -= self.consecutive_failures * 20

        return max(score, 0)


class NitterGateway:
    """Nitter 动态网关 - 支持 Nitter 实例和 RSSHub"""

    # 默认 Nitter 实例列表（按优先级排序）
    DEFAULT_NITTER_INSTANCES = [
        # 首选节点 - 稳定性高
        "https://nitter.privacydev.net",      # 老牌稳定，带宽足
        "https://nitter.moomoo.me",           # 亚洲节点，对中国连接友好
        "https://nitter.net-fi.space",        # 延迟低，适合高频轮询
        # 备用节点
        "https://nitter.perennialte.ch",      # 社区维护，故障恢复快
        "https://nitter.esmailelbob.xyz",     # 更新频率高
        "https://nitter.projectsegfau.lt",    # 隐私导向，较少被封锁
        # 补充节点
        "https://nitter.poast.org",
        "https://nitter.woodland.cafe",
        "https://n.opnxng.com",
        "https://nitter.d420.de",
        "https://nitter.1d4.us",
    ]

    # RSSHub 实例（备用方案，需要自部署才能用 Twitter 路由）
    DEFAULT_RSSHUB_INSTANCES = [
        # "http://localhost:1200",  # 本地自部署
        # "https://rsshub.app",  # 公共实例（Twitter 路由被禁用）
    ]

    def __init__(
        self,
        nitter_instances: Optional[List[str]] = None,
        rsshub_instances: Optional[List[str]] = None,
        timeout: int = 15,
        max_retries: int = 3,
        health_check_interval: int = 300,  # 5 分钟
        rate_limit_cooldown: int = 60,  # 限流冷却 60 秒
        verify_ssl: bool = False,  # 默认不验证 SSL
        prefer_rsshub: bool = False,  # 是否优先使用 RSSHub
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.health_check_interval = health_check_interval
        self.rate_limit_cooldown = rate_limit_cooldown
        self.verify_ssl = verify_ssl
        self.prefer_rsshub = prefer_rsshub

        # 初始化 Nitter 实例
        nitter_urls = nitter_instances or self.DEFAULT_NITTER_INSTANCES
        self.instances: Dict[str, NitterInstance] = {
            url: NitterInstance(url=url) for url in nitter_urls
        }

        # 初始化 RSSHub 实例
        self.rsshub_instances: List[str] = rsshub_instances or self.DEFAULT_RSSHUB_INSTANCES

        # 当前使用的实例索引（轮询用）
        self._current_index = 0
        self._lock = asyncio.Lock()

    def _get_sorted_instances(self) -> List[NitterInstance]:
        """获取按评分排序的实例列表"""
        available = [i for i in self.instances.values() if i.is_available]
        return sorted(available, key=lambda x: x.score, reverse=True)

    def _select_instance(self) -> Optional[NitterInstance]:
        """选择最佳实例"""
        sorted_instances = self._get_sorted_instances()
        if not sorted_instances:
            return None

        # 80% 概率选择最佳实例，20% 概率轮询（避免单点压力）
        import random
        if random.random() < 0.8:
            return sorted_instances[0]
        else:
            return random.choice(sorted_instances)

    def _update_instance_stats(
        self,
        instance: NitterInstance,
        success: bool,
        latency_ms: float = 0,
        rate_limited: bool = False,
    ):
        """更新实例统计"""
        instance.last_check = time.time()

        if rate_limited:
            instance.status = InstanceStatus.RATE_LIMITED
            instance.rate_limit_until = time.time() + self.rate_limit_cooldown
            instance.consecutive_failures += 1
            logger.warning(f"[Nitter] {instance.url} 被限流，冷却 {self.rate_limit_cooldown}s")
            return

        if success:
            instance.success_count += 1
            instance.consecutive_failures = 0

            # 更新平均延迟
            if instance.avg_latency_ms == 0:
                instance.avg_latency_ms = latency_ms
            else:
                instance.avg_latency_ms = (instance.avg_latency_ms * 0.7) + (latency_ms * 0.3)

            # 更新状态
            if latency_ms < 3000:
                instance.status = InstanceStatus.HEALTHY
            else:
                instance.status = InstanceStatus.DEGRADED

        else:
            instance.fail_count += 1
            instance.consecutive_failures += 1

            if instance.consecutive_failures >= 3:
                instance.status = InstanceStatus.UNHEALTHY
                logger.warning(f"[Nitter] {instance.url} 标记为不可用")

    async def fetch_rss(
        self,
        handle: str,
        with_replies: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        获取用户 RSS（优先尝试 RSSHub，失败后尝试 Nitter）

        Args:
            handle: Twitter handle（不含 @）
            with_replies: 是否包含回复

        Returns:
            (rss_content, used_instance_url) 或 (None, None)
        """
        handle = handle.lstrip("@")

        # 如果配置了 RSSHub 且优先使用
        if self.rsshub_instances and self.prefer_rsshub:
            content, url = await self._fetch_via_rsshub(handle, with_replies)
            if content:
                return content, url

        # 尝试 Nitter 实例
        content, url = await self._fetch_via_nitter(handle, with_replies)
        if content:
            return content, url

        # Nitter 失败，尝试 RSSHub 作为备用
        if self.rsshub_instances and not self.prefer_rsshub:
            content, url = await self._fetch_via_rsshub(handle, with_replies)
            if content:
                return content, url

        logger.error(f"[Twitter] {handle} 所有实例均失败")
        return None, None

    async def _fetch_via_rsshub(
        self,
        handle: str,
        with_replies: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        """通过 RSSHub 获取 Twitter RSS"""
        route = f"/twitter/user/{handle}" if not with_replies else f"/twitter/user/{handle}/includeRts=1"

        for rsshub_url in self.rsshub_instances:
            url = f"{rsshub_url}{route}"
            try:
                async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl) as client:
                    response = await client.get(
                        url,
                        headers={"User-Agent": "AInsight/1.0"},
                        follow_redirects=True,
                    )
                    response.raise_for_status()
                    content = response.text

                    if "<rss" in content or "<feed" in content:
                        logger.debug(f"[RSSHub] {handle} 成功 via {rsshub_url}")
                        return content, rsshub_url

            except Exception as e:
                logger.warning(f"[RSSHub] {rsshub_url} 失败: {e}")

        return None, None

    async def _fetch_via_nitter(
        self,
        handle: str,
        with_replies: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        """通过 Nitter 获取 Twitter RSS"""
        path = f"/{handle}/with_replies/rss" if with_replies else f"/{handle}/rss"

        for attempt in range(self.max_retries):
            instance = self._select_instance()
            if not instance:
                logger.error("[Nitter] 无可用实例")
                return None, None

            url = f"{instance.url}{path}"
            start_time = time.time()

            try:
                async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl) as client:
                    response = await client.get(
                        url,
                        headers={
                            "User-Agent": "AInsight/1.0 (RSS Reader)",
                            "Accept": "application/rss+xml, application/xml, text/xml",
                        },
                        follow_redirects=True,
                    )

                    latency_ms = (time.time() - start_time) * 1000

                    # 检查限流
                    if response.status_code == 429:
                        self._update_instance_stats(instance, False, rate_limited=True)
                        continue

                    response.raise_for_status()

                    # 验证是否是有效 RSS
                    content = response.text
                    if "<rss" not in content and "<feed" not in content:
                        logger.warning(f"[Nitter] {instance.url} 返回非 RSS 内容")
                        self._update_instance_stats(instance, False)
                        continue

                    self._update_instance_stats(instance, True, latency_ms)
                    logger.debug(f"[Nitter] {handle} via {instance.url} ({latency_ms:.0f}ms)")
                    return content, instance.url

            except httpx.TimeoutException:
                logger.warning(f"[Nitter] {instance.url} 超时")
                self._update_instance_stats(instance, False)

            except httpx.HTTPStatusError as e:
                logger.warning(f"[Nitter] {instance.url} HTTP {e.response.status_code}")
                if e.response.status_code == 429:
                    self._update_instance_stats(instance, False, rate_limited=True)
                else:
                    self._update_instance_stats(instance, False)

            except Exception as e:
                logger.warning(f"[Nitter] {instance.url} 错误: {e}")
                self._update_instance_stats(instance, False)

        logger.error(f"[Nitter] {handle} 所有实例均失败")
        return None, None

    async def fetch_search(
        self,
        query: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        获取搜索 RSS

        Args:
            query: 搜索关键词

        Returns:
            (rss_content, used_instance_url) 或 (None, None)
        """
        from urllib.parse import quote
        path = f"/search/rss?f=tweets&q={quote(query)}"

        for attempt in range(self.max_retries):
            instance = self._select_instance()
            if not instance:
                return None, None

            url = f"{instance.url}{path}"
            start_time = time.time()

            try:
                async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_ssl) as client:
                    response = await client.get(
                        url,
                        headers={"User-Agent": "AInsight/1.0"},
                        follow_redirects=True,
                    )

                    latency_ms = (time.time() - start_time) * 1000

                    if response.status_code == 429:
                        self._update_instance_stats(instance, False, rate_limited=True)
                        continue

                    response.raise_for_status()
                    content = response.text

                    if "<rss" not in content and "<feed" not in content:
                        self._update_instance_stats(instance, False)
                        continue

                    self._update_instance_stats(instance, True, latency_ms)
                    return content, instance.url

            except Exception as e:
                logger.warning(f"[Nitter] 搜索失败 {instance.url}: {e}")
                self._update_instance_stats(instance, False)

        return None, None

    async def health_check(self) -> Dict[str, dict]:
        """
        健康检查所有实例

        Returns:
            实例状态字典
        """
        results = {}

        async def check_instance(instance: NitterInstance):
            url = f"{instance.url}/jack/rss"  # 用 @jack 测试
            start_time = time.time()

            try:
                async with httpx.AsyncClient(timeout=10, verify=self.verify_ssl) as client:
                    response = await client.get(url, follow_redirects=True)
                    latency_ms = (time.time() - start_time) * 1000

                    if response.status_code == 200 and "<rss" in response.text:
                        self._update_instance_stats(instance, True, latency_ms)
                        return {
                            "status": "healthy",
                            "latency_ms": latency_ms,
                        }
                    elif response.status_code == 429:
                        self._update_instance_stats(instance, False, rate_limited=True)
                        return {"status": "rate_limited"}
                    else:
                        self._update_instance_stats(instance, False)
                        return {"status": "unhealthy", "code": response.status_code}

            except Exception as e:
                self._update_instance_stats(instance, False)
                return {"status": "error", "error": str(e)}

        tasks = []
        for instance in self.instances.values():
            tasks.append((instance.url, check_instance(instance)))

        for url, task in tasks:
            results[url] = await task

        return results

    def get_stats(self) -> Dict[str, dict]:
        """获取所有实例统计"""
        return {
            url: {
                "status": inst.status.value,
                "score": round(inst.score, 1),
                "success": inst.success_count,
                "fail": inst.fail_count,
                "avg_latency_ms": round(inst.avg_latency_ms, 0),
                "consecutive_failures": inst.consecutive_failures,
                "is_available": inst.is_available,
            }
            for url, inst in self.instances.items()
        }

    def add_instance(self, url: str):
        """添加新实例"""
        if url not in self.instances:
            self.instances[url] = NitterInstance(url=url)
            logger.info(f"[Nitter] 添加实例: {url}")

    def remove_instance(self, url: str):
        """移除实例"""
        if url in self.instances:
            del self.instances[url]
            logger.info(f"[Nitter] 移除实例: {url}")

    def add_rsshub_instance(self, url: str):
        """添加 RSSHub 实例"""
        if url not in self.rsshub_instances:
            self.rsshub_instances.append(url)
            logger.info(f"[RSSHub] 添加实例: {url}")

    def set_prefer_rsshub(self, prefer: bool):
        """设置是否优先使用 RSSHub"""
        self.prefer_rsshub = prefer


# 全局单例
_gateway: Optional[NitterGateway] = None


def get_nitter_gateway(
    nitter_instances: Optional[List[str]] = None,
    rsshub_instances: Optional[List[str]] = None,
    **kwargs
) -> NitterGateway:
    """获取 Nitter 网关单例"""
    global _gateway
    if _gateway is None:
        _gateway = NitterGateway(
            nitter_instances=nitter_instances,
            rsshub_instances=rsshub_instances,
            **kwargs
        )
    return _gateway


def reset_nitter_gateway():
    """重置网关单例（用于测试）"""
    global _gateway
    _gateway = None


async def test_nitter_gateway():
    """测试 Nitter 网关"""
    gateway = get_nitter_gateway()

    print("=" * 60)
    print("Nitter 动态网关测试")
    print("=" * 60)

    # 健康检查
    print("\n1. 健康检查...")
    health = await gateway.health_check()
    for url, status in health.items():
        print(f"  {url}: {status}")

    # 测试抓取
    print("\n2. 测试抓取 @elonmusk...")
    content, used_url = await gateway.fetch_rss("elonmusk")
    if content:
        print(f"  ✅ 成功 via {used_url}")
        print(f"  内容长度: {len(content)} bytes")
    else:
        print("  ❌ 失败")

    # 统计
    print("\n3. 实例统计:")
    stats = gateway.get_stats()
    for url, stat in stats.items():
        print(f"  {url}:")
        print(f"    状态: {stat['status']}, 评分: {stat['score']}")
        print(f"    成功/失败: {stat['success']}/{stat['fail']}")


if __name__ == "__main__":
    asyncio.run(test_nitter_gateway())
