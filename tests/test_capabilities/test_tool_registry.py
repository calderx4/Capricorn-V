import pytest
from typing import Any, Dict

from capabilities.tools.registry import ToolRegistry
from core.base_tool import BaseTool


class _EchoTool(BaseTool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo input"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, text: str = "", **kwargs):
        return text


class _AddTool(BaseTool):
    @property
    def name(self) -> str:
        return "add"

    @property
    def description(self) -> str:
        return "Add numbers"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        }

    async def execute(self, a: int = 0, b: int = 0, **kwargs):
        return a + b


class TestToolRegistry:
    def setup_method(self):
        self.registry = ToolRegistry()
        self.echo = _EchoTool()
        self.add = _AddTool()

    def test_register_and_has(self):
        self.registry.register(self.echo)
        assert self.registry.has("echo")
        assert not self.registry.has("nonexistent")

    def test_list_tools(self):
        self.registry.register(self.echo)
        self.registry.register(self.add, layer="builtin")
        tools = self.registry.list_tools()
        assert "echo" in tools
        assert "add" in tools

    def test_len(self):
        assert len(self.registry) == 0
        self.registry.register(self.echo)
        assert len(self.registry) == 1

    def test_contains(self):
        self.registry.register(self.echo)
        assert "echo" in self.registry
        assert "missing" not in self.registry

    def test_unregister(self):
        self.registry.register(self.echo)
        self.registry.unregister("echo")
        assert not self.registry.has("echo")

    def test_get(self):
        self.registry.register(self.echo)
        assert self.registry.get("echo") is self.echo
        assert self.registry.get("missing") is None

    def test_list_by_layer(self):
        self.registry.register(self.echo, layer="builtin")
        self.registry.register(self.add, layer="mcp")
        layers = self.registry.list_by_layer()
        assert "echo" in layers["builtin"]
        assert "add" in layers["mcp"]


class TestToolExecution:
    def setup_method(self):
        self.registry = ToolRegistry()
        self.echo = _EchoTool()
        self.add = _AddTool()
        self.registry.register(self.echo)
        self.registry.register(self.add)

    @pytest.mark.asyncio
    async def test_execute_success(self):
        result = await self.registry.execute("echo", {"text": "hello"})
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_execute_with_type_cast(self):
        result = await self.registry.execute("add", {"a": "3", "b": "4"})
        assert result == 7

    @pytest.mark.asyncio
    async def test_execute_not_found(self):
        result = await self.registry.execute("missing", {})
        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_execute_missing_required(self):
        result = await self.registry.execute("echo", {})
        assert "Error" in result
        assert "Missing required" in result

    @pytest.mark.asyncio
    async def test_execute_batch(self):
        results = await self.registry.execute_batch([
            {"name": "echo", "arguments": {"text": "a"}},
            {"name": "echo", "arguments": {"text": "b"}},
        ])
        assert results == ["a", "b"]
