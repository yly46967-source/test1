"""
SimHash 去重模块 - 基于内容相似度的去重

SimHash 是一种局部敏感哈希算法，用于检测近似重复内容。
相比 MD5/SHA256，SimHash 可以检测出内容相似但不完全相同的文本。
"""
import re
import hashlib
from typing import List, Tuple, Optional, Set
from collections import defaultdict

from src.logger import get_logger

logger = get_logger(__name__)


class SimHash:
    """SimHash 实现"""

    def __init__(self, hash_bits: int = 64):
        """
        初始化 SimHash

        Args:
            hash_bits: 哈希位数，默认 64 位
        """
        self.hash_bits = hash_bits

    def _tokenize(self, text: str) -> List[str]:
        """分词：提取 n-gram 特征"""
        # 清理文本
        text = text.lower().strip()
        # 移除 URL
        text = re.sub(r'https?://\S+', '', text)
        # 移除特殊字符，保留字母、数字、中文
        text = re.sub(r'[^\w\u4e00-\u9fa5\s]', ' ', text)

        tokens = []

        # 英文单词
        words = re.findall(r'[a-z]+', text)
        tokens.extend(words)

        # 中文 2-gram
        chinese = re.findall(r'[\u4e00-\u9fa5]+', text)
        for segment in chinese:
            for i in range(len(segment) - 1):
                tokens.append(segment[i:i+2])

        # 3-gram（混合）
        all_text = re.sub(r'\s+', '', text)
        for i in range(len(all_text) - 2):
            tokens.append(all_text[i:i+3])

        return tokens

    def _hash_token(self, token: str) -> int:
        """计算单个 token 的哈希值"""
        h = hashlib.md5(token.encode('utf-8')).hexdigest()
        return int(h, 16) % (2 ** self.hash_bits)

    def compute(self, text: str) -> int:
        """
        计算文本的 SimHash 值

        Args:
            text: 输入文本

        Returns:
            SimHash 值（整数）
        """
        if not text:
            return 0

        tokens = self._tokenize(text)
        if not tokens:
            return 0

        # 初始化向量
        v = [0] * self.hash_bits

        # 计算每个 token 的贡献
        for token in tokens:
            token_hash = self._hash_token(token)
            for i in range(self.hash_bits):
                if token_hash & (1 << i):
                    v[i] += 1
                else:
                    v[i] -= 1

        # 生成最终哈希
        fingerprint = 0
        for i in range(self.hash_bits):
            if v[i] > 0:
                fingerprint |= (1 << i)

        return fingerprint

    def distance(self, hash1: int, hash2: int) -> int:
        """
        计算两个 SimHash 的汉明距离

        Args:
            hash1: 第一个哈希值
            hash2: 第二个哈希值

        Returns:
            汉明距离（不同位的数量）
        """
        x = hash1 ^ hash2
        distance = 0
        while x:
            distance += 1
            x &= x - 1
        return distance

    def similarity(self, hash1: int, hash2: int) -> float:
        """
        计算两个 SimHash 的相似度

        Args:
            hash1: 第一个哈希值
            hash2: 第二个哈希值

        Returns:
            相似度 0-1
        """
        dist = self.distance(hash1, hash2)
        return 1 - (dist / self.hash_bits)


class ContentDeduplicator:
    """内容去重器 - URL + SimHash 双重过滤"""

    def __init__(
        self,
        simhash_threshold: float = 0.85,  # SimHash 相似度阈值
        hash_bits: int = 64,
    ):
        """
        初始化去重器

        Args:
            simhash_threshold: SimHash 相似度阈值，>= 此值视为重复
            hash_bits: SimHash 位数
        """
        self.simhash = SimHash(hash_bits=hash_bits)
        self.threshold = simhash_threshold

        # 内存缓存（用于批量处理）
        self._url_hashes: Set[str] = set()
        self._simhashes: List[Tuple[int, str]] = []  # (simhash, url_hash)

    def _hash_url(self, url: str) -> str:
        """计算 URL 哈希"""
        # 标准化 URL
        url = url.lower().strip()
        # 移除常见的追踪参数
        url = re.sub(r'[?&](utm_\w+|ref|source|fbclid|gclid)=[^&]*', '', url)
        return hashlib.sha256(url.encode()).hexdigest()

    def is_duplicate(
        self,
        url: str,
        text: str,
        existing_url_hashes: Optional[Set[str]] = None,
        existing_simhashes: Optional[List[Tuple[int, str]]] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        检查内容是否重复

        Args:
            url: 内容 URL
            text: 内容文本
            existing_url_hashes: 已存在的 URL 哈希集合
            existing_simhashes: 已存在的 SimHash 列表

        Returns:
            (is_duplicate, reason, matched_url_hash)
        """
        url_hash = self._hash_url(url)

        # 1. URL 精确匹配
        all_url_hashes = existing_url_hashes or set()
        all_url_hashes.update(self._url_hashes)

        if url_hash in all_url_hashes:
            return True, "url_exact_match", url_hash

        # 2. SimHash 相似度检查
        content_simhash = self.simhash.compute(text)

        all_simhashes = existing_simhashes or []
        all_simhashes.extend(self._simhashes)

        for existing_hash, existing_url_hash in all_simhashes:
            similarity = self.simhash.similarity(content_simhash, existing_hash)
            if similarity >= self.threshold:
                logger.debug(f"SimHash 相似度 {similarity:.2f} >= {self.threshold}")
                return True, f"simhash_similar_{similarity:.2f}", existing_url_hash

        # 3. 不重复，添加到缓存
        self._url_hashes.add(url_hash)
        self._simhashes.append((content_simhash, url_hash))

        return False, "unique", None

    def batch_deduplicate(
        self,
        contents: List[dict],
        existing_url_hashes: Optional[Set[str]] = None,
        existing_simhashes: Optional[List[Tuple[int, str]]] = None,
    ) -> Tuple[List[dict], List[dict]]:
        """
        批量去重

        Args:
            contents: 内容列表，每个包含 source_url 和 text
            existing_url_hashes: 已存在的 URL 哈希
            existing_simhashes: 已存在的 SimHash

        Returns:
            (unique_contents, duplicate_contents)
        """
        unique = []
        duplicates = []

        for content in contents:
            url = content.get("source_url", "")
            text = content.get("text", "")

            is_dup, reason, matched = self.is_duplicate(
                url, text, existing_url_hashes, existing_simhashes
            )

            if is_dup:
                content["_dedup_reason"] = reason
                content["_dedup_matched"] = matched
                duplicates.append(content)
            else:
                unique.append(content)

        logger.info(f"去重结果: {len(unique)} 唯一, {len(duplicates)} 重复")
        return unique, duplicates

    def clear_cache(self):
        """清空内存缓存"""
        self._url_hashes.clear()
        self._simhashes.clear()

    def get_simhash(self, text: str) -> int:
        """获取文本的 SimHash 值"""
        return self.simhash.compute(text)

    def compare_texts(self, text1: str, text2: str) -> float:
        """比较两段文本的相似度"""
        hash1 = self.simhash.compute(text1)
        hash2 = self.simhash.compute(text2)
        return self.simhash.similarity(hash1, hash2)


def test_simhash():
    """测试 SimHash"""
    dedup = ContentDeduplicator(simhash_threshold=0.8)

    # 测试相似文本
    text1 = "OpenAI 发布了 GPT-5，这是一个重大突破"
    text2 = "OpenAI 今天发布 GPT-5，这是 AI 领域的重大突破"
    text3 = "苹果公司发布了新款 iPhone 15"

    sim_1_2 = dedup.compare_texts(text1, text2)
    sim_1_3 = dedup.compare_texts(text1, text3)

    print(f"文本1 vs 文本2 相似度: {sim_1_2:.2f}")
    print(f"文本1 vs 文本3 相似度: {sim_1_3:.2f}")

    # 测试去重
    contents = [
        {"source_url": "https://example.com/1", "text": text1},
        {"source_url": "https://example.com/2", "text": text2},
        {"source_url": "https://example.com/3", "text": text3},
        {"source_url": "https://example.com/1?utm_source=twitter", "text": text1},  # URL 重复
    ]

    unique, dups = dedup.batch_deduplicate(contents)
    print(f"\n去重结果: {len(unique)} 唯一, {len(dups)} 重复")
    for d in dups:
        print(f"  重复: {d['source_url']} - {d['_dedup_reason']}")


if __name__ == "__main__":
    test_simhash()
