"""
MCP Client Manager - MCP 服务器连接和工具注册

支持多种传输方式：
- stdio: 标准输入输出
- sse: Server-Sent Events
- streamable_http: 流式 HTTP
"""

import asyncio
from contextlib import AsyncExitStack
from typing import Any, Dict
from loguru import logger

from config.settings import Config, MCPServerConfig
from capabilities.tools.registry import ToolRegistry
from .mcp_wrapper import MCPToolWrapper


def _resolve_headers(headers: Dict[str, Any]) -> Dict[str, Any]:
    """解析 headers 中所有环境变量"""
    if not headers:
        return {}
    return Config._resolve_env_vars(headers)


class MCPClientManager:
    """MCP 客户端管理器"""

    def __init__(self, mcp_servers: Dict[str, MCPServerConfig]):
        """
        初始化 MCP 客户端管理器

        Args:
            mcp_servers: MCP 服务器配置字典
        """
        self.mcp_servers = mcp_servers
        self._stack: AsyncExitStack = None

    async def connect(self, registry: ToolRegistry, layer: str = "mcp") -> int:
        """
        连接所有 MCP 服务器并注册工具

        Args:
            registry: 工具注册表
            layer: 工具层级（mcp）

        Returns:
            注册的工具数量
        """
        if not self.mcp_servers:
            return 0

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.sse import sse_client
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamable_http_client

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()

        total_tools = 0

        for name, cfg in self.mcp_servers.items():
            if not cfg.enabled:
                logger.debug(f"MCP server '{name}': disabled, skipping")
                continue

            try:
                transport_type = cfg.type

                # 根据传输类型连接
                if transport_type == "stdio":
                    read, write = await self._stack.enter_async_context(
                        stdio_client(
                            StdioServerParameters(
                                command=cfg.command,
                                args=cfg.args,
                                env=cfg.env or None
                            )
                        )
                    )
                elif transport_type == "sse":
                    import httpx
                    resolved_headers = _resolve_headers(cfg.headers)

                    def httpx_client_factory(
                        headers: dict = None,
                        timeout: httpx.Timeout = None,
                        auth: httpx.Auth = None
                    ):
                        merged_headers = {**resolved_headers, **(headers or {})}
                        return httpx.AsyncClient(
                            headers=merged_headers or None,
                            follow_redirects=True,
                            timeout=timeout,
                            auth=auth
                        )

                    read, write = await self._stack.enter_async_context(
                        sse_client(cfg.url, httpx_client_factory=httpx_client_factory)
                    )
                elif transport_type == "streamable_http":
                    import httpx
                    resolved_headers = _resolve_headers(cfg.headers)

                    http_client = await self._stack.enter_async_context(
                        httpx.AsyncClient(
                            headers=resolved_headers or None,
                            follow_redirects=True,
                            timeout=httpx.Timeout(30.0, connect=10.0)
                        )
                    )
                    read, write, _ = await self._stack.enter_async_context(
                        streamable_http_client(cfg.url, http_client=http_client)
                    )
                else:
                    logger.warning(f"MCP server '{name}': unknown transport type '{transport_type}'")
                    continue

                # 创建会话
                session = await self._stack.enter_async_context(ClientSession(read, write))
                await session.initialize()

                # 获取工具列表
                tools = await session.list_tools()

                # 过滤启用的工具
                enabled_tools = set(cfg.enabled_tools)
                allow_all_tools = "*" in enabled_tools

                registered_count = 0

                # 注册工具
                server_lock = asyncio.Lock()
                for tool_def in tools.tools:
                    wrapped_name = f"mcp_{name}_{tool_def.name}"

                    # 检查工具是否在启用列表中
                    if not allow_all_tools and tool_def.name not in enabled_tools and wrapped_name not in enabled_tools:
                        continue

                    # 创建工具包装器并注册
                    wrapper = MCPToolWrapper(session, name, tool_def, tool_timeout=cfg.tool_timeout, lock=server_lock)
                    registry.register(wrapper, layer=layer)
                    registered_count += 1

                total_tools += registered_count
                logger.info(f"✓ MCP server '{name}': connected, {registered_count} tools registered")

            except Exception as e:
                logger.error(f"✗ MCP server '{name}': failed to connect: {e}")

        return total_tools

    async def disconnect(self):
        """断开所有 MCP 连接"""
        if self._stack:
            try:
                await self._stack.aclose()
            except Exception as e:
                logger.warning(f"Error during MCP disconnect: {e}")
            self._stack = None
            logger.info("MCP connections closed")
