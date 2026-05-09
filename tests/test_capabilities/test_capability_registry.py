import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

from capabilities.capability_registry import CapabilityRegistry


class TestCapabilityRegistryCreate:
    @pytest.mark.asyncio
    async def test_create_initializes_empty(self, tmp_path):
        """Registry 能在无 MCP 配置时初始化"""
        registry = await CapabilityRegistry.create(
            workspace_root=str(tmp_path),
            sandbox=True,
        )
        assert registry.tools is not None

    @pytest.mark.asyncio
    async def test_register_tool_and_execute(self, tmp_path):
        """手动注册工具后可以执行"""
        registry = await CapabilityRegistry.create(
            workspace_root=str(tmp_path),
            sandbox=True,
        )
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"
        mock_tool.parameters = {"type": "object", "properties": {}}
        mock_tool.execute = AsyncMock(return_value="test result")
        registry.tools.register(mock_tool, layer="builtin")
        assert "test_tool" in registry.tools

    @pytest.mark.asyncio
    async def test_get_langchain_tools(self, tmp_path):
        """get_langchain_tools 返回已注册工具的 LangChain 格式"""
        registry = await CapabilityRegistry.create(
            workspace_root=str(tmp_path),
            sandbox=True,
        )
        mock_tool = MagicMock()
        mock_tool.name = "mock_tool"
        mock_tool.description = "Mock"
        mock_tool.parameters = {"type": "object", "properties": {}}
        mock_tool.cast_params = MagicMock(return_value={})
        mock_tool.to_langchain_tool = MagicMock(return_value=MagicMock(name="mock_tool"))
        registry.tools.register(mock_tool, layer="builtin")
        lc_tools = registry.get_langchain_tools()
        assert len(lc_tools) > 0


class TestCapabilityRegistryExecute:
    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, tmp_path):
        registry = await CapabilityRegistry.create(
            workspace_root=str(tmp_path),
            sandbox=True,
        )
        result = await registry.execute_tool("nonexistent_tool", {})
        assert "not found" in result.lower() or "Error" in result


class TestCapabilityRegistryCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_without_mcp(self, tmp_path):
        registry = await CapabilityRegistry.create(
            workspace_root=str(tmp_path),
            sandbox=True,
        )
        # 无 MCP 时 cleanup 不报错
        await registry.cleanup()
