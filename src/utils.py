"""工具函数模块"""
import asyncio
import functools
import random
from typing import TypeVar, Callable, Any
from src.logger import get_logger

logger = get_logger("utils")

T = TypeVar("T")


def retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Callable[[Exception, int], None] = None,
):
    """
    异步重试装饰器

    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff: 延迟时间的指数增长因子
        exceptions: 需要重试的异常类型
        on_retry: 重试时的回调函数 (exception, attempt)

    Example:
        @retry(max_retries=3, delay=1.0)
        async def fetch_data():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None
            current_delay = delay

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt < max_retries:
                        # 添加随机抖动，避免雷群效应
                        jitter = random.uniform(0, current_delay * 0.1)
                        wait_time = current_delay + jitter

                        if on_retry:
                            on_retry(e, attempt + 1)
                        else:
                            logger.warning(
                                f"重试 {attempt + 1}/{max_retries}: {func.__name__} - {e}"
                            )

                        await asyncio.sleep(wait_time)
                        current_delay *= backoff

            # 所有重试都失败
            raise last_exception

        return wrapper
    return decorator


class Semaphore:
    """
    并发控制信号量包装器

    Example:
        sem = Semaphore(5)  # 最多 5 个并发

        async def task():
            async with sem:
                await do_something()
    """
    def __init__(self, limit: int):
        self._semaphore = asyncio.Semaphore(limit)
        self.limit = limit

    async def __aenter__(self):
        await self._semaphore.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._semaphore.release()


async def gather_with_concurrency(
    limit: int,
    *tasks,
    return_exceptions: bool = True,
) -> list:
    """
    带并发限制的 asyncio.gather

    Args:
        limit: 最大并发数
        *tasks: 协程任务列表
        return_exceptions: 是否返回异常而不是抛出

    Returns:
        任务结果列表

    Example:
        results = await gather_with_concurrency(
            5,
            fetch_source_1(),
            fetch_source_2(),
            fetch_source_3(),
        )
    """
    semaphore = asyncio.Semaphore(limit)

    async def limited_task(task):
        async with semaphore:
            return await task

    return await asyncio.gather(
        *[limited_task(task) for task in tasks],
        return_exceptions=return_exceptions,
    )
