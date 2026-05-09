import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from agent.agent import CapricornGraph


def _make_mock_graph(max_iterations=50):
    """构造 CapricornGraph 实例，用 mock 替代所有依赖"""
    graph = object.__new__(CapricornGraph)
    graph.capability_registry = MagicMock()
    graph.capability_registry.tools = MagicMock()
    graph.capability_registry.tools.execute = AsyncMock(return_value="ok")
    graph.capability_registry.get_langchain_tools = MagicMock(return_value=[])
    graph.capability_registry.tools.get_langchain_tools = MagicMock(return_value=[])
    graph.skill_manager = MagicMock()
    graph.session_manager = MagicMock()
    graph.long_term_memory = MagicMock()
    graph.long_term_memory.read = MagicMock(return_value="")
    graph.history_log = MagicMock()
    graph.history_log.read = MagicMock(return_value=[])
    graph.llm_client = MagicMock()
    graph.sandbox = True
    graph.max_iterations = max_iterations
    graph._llm_with_tools = MagicMock()
    return graph


class TestDictToMessage:
    def setup_method(self):
        self.graph = _make_mock_graph()

    def test_user_role(self):
        msg = {"role": "user", "content": "hello"}
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, HumanMessage)
        assert result.content == "hello"

    def test_system_role(self):
        msg = {"role": "system", "content": "you are helpful"}
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, SystemMessage)

    def test_assistant_role(self):
        msg = {"role": "assistant", "content": "response"}
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, AIMessage)

    def test_tool_role(self):
        msg = {"role": "tool", "content": "file content", "tool_call_id": "call_123"}
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, ToolMessage)
        assert result.tool_call_id == "call_123"
        assert result.content == "file content"

    def test_assistant_with_tool_calls(self):
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "name": "read_file", "args": {"path": "test.py"}}
            ],
        }
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, AIMessage)
        assert result.tool_calls == msg["tool_calls"]

    def test_default_role_falls_back_to_ai(self):
        msg = {"role": "unknown", "content": "something"}
        result = self.graph._dict_to_message(msg)
        assert isinstance(result, AIMessage)


class TestExtractContent:
    def setup_method(self):
        self.graph = _make_mock_graph()

    def test_string_content(self):
        msg = AIMessage(content="hello")
        assert self.graph._extract_content(msg) == "hello"

    def test_list_content_with_text_blocks(self):
        msg = AIMessage(content=[
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "World"},
        ])
        assert "Hello" in self.graph._extract_content(msg)

    def test_thinking_tags_stripped(self):
        msg = AIMessage(content="<thinking>inner thought</thinking>actual response")
        result = self.graph._extract_content(msg)
        assert "<thinking>" not in result
        assert "actual response" in result


class TestSummarizeMessages:
    def setup_method(self):
        self.graph = _make_mock_graph()

    def test_summary_format(self):
        messages = [
            SystemMessage(content="system"),
            HumanMessage(content="hello"),
            AIMessage(content="response"),
        ]
        summary = self.graph._summarize_messages(messages)
        assert "共 3 条" in summary
        assert "SystemMessage" in summary
        assert "HumanMessage" in summary
