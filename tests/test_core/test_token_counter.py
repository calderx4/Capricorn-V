import pytest

from core.token_counter import TokenCounter, fallback_estimate


class TestEstimateTokens:
    def test_empty_string(self):
        assert TokenCounter.estimate_tokens("") == 0

    def test_non_empty_string(self):
        count = TokenCounter.estimate_tokens("Hello, world!")
        assert count > 0

    def test_chinese_text(self):
        count = TokenCounter.estimate_tokens("你好世界测试")
        assert count > 0


class TestCountMessagesTokens:
    def test_empty_list(self):
        assert TokenCounter.count_messages_tokens([]) == 0

    def test_string_content(self):
        messages = [{"role": "user", "content": "Hello"}]
        count = TokenCounter.count_messages_tokens(messages)
        assert count > 0

    def test_list_content(self):
        messages = [
            {"role": "assistant", "content": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": "World"},
            ]}
        ]
        count = TokenCounter.count_messages_tokens(messages)
        assert count > 0

    def test_mixed_messages(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello there!"},
        ]
        count = TokenCounter.count_messages_tokens(messages)
        assert count > 0


class TestFallbackEstimate:
    def test_empty_string(self):
        assert fallback_estimate("") == 0

    def test_english_text(self):
        estimate = fallback_estimate("Hello world")
        assert estimate > 0

    def test_chinese_text(self):
        estimate = fallback_estimate("你好世界")
        assert estimate > 0

    def test_chinese_dense_text_uses_2_ratio(self):
        text = "你好世界测试中文内容" * 10
        estimate = fallback_estimate(text)
        assert estimate == int(len(text) / 2)

    def test_english_text_uses_4_ratio(self):
        text = "Hello world test" * 10
        estimate = fallback_estimate(text)
        assert estimate == int(len(text) / 4)
