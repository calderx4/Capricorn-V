"""
Token Counter - Token 计数工具

统一提供字符串和消息列表的 token 计数。
优先使用 tiktoken 精确计数，失败时降级到启发式估算。
"""

from typing import Dict, List

from loguru import logger

try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False


class TokenCounter:
    """Token 计数器 - tiktoken 精确计数 + 启发式降级"""

    _encoder = None  # 缓存 encoder 实例

    @classmethod
    def _get_encoder(cls):
        """获取或创建 tiktoken encoder（惰性加载，全局缓存）"""
        if cls._encoder is None:
            try:
                cls._encoder = tiktoken.get_encoding("cl100k_base")
            except Exception as e:
                logger.warning(f"Failed to load tiktoken, using fallback: {e}")
                cls._encoder = False  # 标记失败
        return cls._encoder if cls._encoder else None

    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        """
        计算 token 数量

        优先使用 tiktoken，失败时降级到启发式估算
        """
        if not text:
            return 0

        encoder = cls._get_encoder()
        if encoder:
            try:
                return len(encoder.encode(text))
            except Exception as e:
                logger.debug(f"tiktoken encode failed: {e}")

        # Fallback: 启发式估算
        return fallback_estimate(text)

    @classmethod
    def count_messages_tokens(cls, messages: List[Dict]) -> int:
        """计算消息列表的总 token 数"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += cls.estimate_tokens(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        total += cls.estimate_tokens(block.get("text", ""))
        return total


def fallback_estimate(text: str) -> int:
    """
    启发式 token 估算

    中文约 1.5 字符/token，英文约 4 字符/token
    """
    if not text:
        return 0

    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total_chars = len(text)

    if total_chars > 0 and chinese_chars / total_chars > 0.3:
        return int(total_chars / 2)
    return int(total_chars / 4)



