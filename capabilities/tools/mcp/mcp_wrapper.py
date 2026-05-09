"""
MCP Tool Wrapper - MCP 工具包装器

将 MCP 工具包装成 BaseTool 格式。
同一 server 的所有 wrapper 共享一个 asyncio.Lock，防止并发调用导致协议帧交叉。
"""

import asyncio
from typing import Any, Dict
from loguru import logger

from core.base_tool import BaseTool


class MCPToolWrapper(BaseTool):
    """MCP 工具包装器"""

    def __init__(self, session, server_name: str, tool_def, tool_timeout: int = 30,
                 lock: asyncio.Lock = None):
        """
        初始化 MCP 工具包装器

        Args:
            session: MCP 会话
            server_name: 服务器名称
            tool_def: 工具定义
            tool_timeout: 超时时间（秒）
            lock: 同一 server 的共享锁（防止并发调用协议帧交叉）
        """
        self._session = session
        self._original_name = tool_def.name
        self._name = f"mcp_{server_name}_{tool_def.name}"
        self._description = (
            tool_def.description
            or f"MCP tool: {tool_def.name} from {server_name} server"
        )
        raw_schema = tool_def.inputSchema or {"type": "object", "properties": {}}
        self._parameters = self._normalize_schema(raw_schema)
        self._tool_timeout = tool_timeout
        self._lock = lock

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        """执行 MCP 工具（通过共享锁串行化同一 server 的并发调用）"""
        async def _call():
            return await asyncio.wait_for(
                self._session.call_tool(self._original_name, arguments=kwargs),
                timeout=self._tool_timeout,
            )

        try:
            if self._lock:
                async with self._lock:
                    result = await _call()
            else:
                result = await _call()
            return self._parse_result(result)
        except asyncio.TimeoutError:
            logger.error(f"MCP tool '{self._name}' timed out after {self._tool_timeout}s")
            return f"Error: MCP tool call timed out after {self._tool_timeout}s"
        except Exception as exc:
            logger.error(f"MCP tool '{self._name}' failed: {exc}")
            return f"Error: MCP tool call failed: {type(exc).__name__}: {str(exc)}"

    def _normalize_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        规范化 JSON Schema

        确保 Schema 符合标准格式。

        Args:
            schema: 原始 Schema

        Returns:
            规范化后的 Schema（拷贝，不修改原字典）
        """
        schema = dict(schema)

        if "type" not in schema:
            schema["type"] = "object"

        if schema.get("type") == "object" and "properties" not in schema:
            schema["properties"] = {}

        if "required" in schema and not isinstance(schema["required"], list):
            schema["required"] = []

        return schema

    def _parse_result(self, result: Any) -> str:
        """
        解析 MCP 工具调用结果

        Args:
            result: MCP 返回的结果

        Returns:
            字符串格式的结果
        """
        if isinstance(result, str):
            return result

        if isinstance(result, dict):
            # 尝试提取文本内容
            if "content" in result:
                content = result["content"]
                if isinstance(content, list):
                    # 处理内容列表
                    texts = []
                    for item in content:
                        if isinstance(item, dict) and "text" in item:
                            texts.append(item["text"])
                    return "\n".join(texts)
                return str(content)
            return str(result)

        return str(result)
