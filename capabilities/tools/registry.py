"""
Tool Registry - 工具注册和执行

参考 nanobot 实现：
- 统一注册
- 并发执行
- 错误处理
"""

import asyncio
import json
from typing import Dict, List, Any, Optional
from loguru import logger

from core.base_tool import BaseTool


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._layers: Dict[str, str] = {}  # public_name -> layer
        self._public_names: Dict[str, str] = {}  # public_name -> internal tool.name
        self._vertical_map: Dict[str, str] = {}  # public_name -> vertical_name

    def register(self, tool: BaseTool, layer: str = "builtin", public_name: str = None, vertical_name: str = None) -> None:
        """注册工具"""
        try:
            schema = tool.parameters
            if not isinstance(schema, dict):
                logger.warning(f"Tool '{tool.name}' has invalid schema type: {type(schema)}")
            elif "type" not in schema:
                logger.warning(f"Tool '{tool.name}' schema missing 'type' field")

            public_name = public_name or tool.name
            if public_name in self._tools:
                existing_layer = self._layers.get(public_name, "?")
                existing_vertical = self._vertical_map.get(public_name, "")
                raise ValueError(
                    f"Tool name conflict: '{public_name}' already registered "
                    f"[{existing_layer}]{f' vertical={existing_vertical}' if existing_vertical else ''}. "
                    f"Each vertical must be loaded independently."
                )
            self._tools[public_name] = tool
            self._layers[public_name] = layer
            self._public_names[public_name] = tool.name
            if vertical_name:
                self._vertical_map[public_name] = vertical_name
            logger.debug(f"✓ Registered [{layer}] tool: {public_name}")

        except Exception as e:
            logger.error(f"Failed to register tool '{tool.name}': {e}")
            raise

    def unregister(self, name: str) -> None:
        """注销工具"""
        self._tools.pop(name, None)
        self._layers.pop(name, None)
        self._public_names.pop(name, None)
        self._vertical_map.pop(name, None)

    def get(self, name: str) -> Optional[BaseTool]:
        """获取工具"""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """检查工具是否存在"""
        return name in self._tools

    def list_tools(self) -> List[str]:
        """列出所有工具"""
        return list(self._tools.keys())

    def list_by_layer(self) -> Dict[str, List[str]]:
        """按层级列出工具"""
        layers = {"builtin": [], "mcp": [], "workflow": [], "vertical": []}
        for name, layer in self._layers.items():
            if layer in layers:
                layers[layer].append(name)
            else:
                layers[layer] = [name]
        return layers

    def unregister_by_vertical(self, vertical_name: str) -> None:
        """注销某个垂类的所有 tools"""
        to_remove = [
            name for name, vname in self._vertical_map.items()
            if vname == vertical_name
        ]
        for name in to_remove:
            self.unregister(name)

    def get_langchain_tools(self) -> List:
        """获取所有工具的 LangChain 格式（使用 public_name）"""
        result = []
        for public_name, tool in self._tools.items():
            lc_tool = tool.to_langchain_tool()
            if public_name != tool.name:
                lc_tool.name = public_name
            result.append(lc_tool)
        return result

    async def execute(self, name: str, params: Dict[str, Any]) -> Any:
        """执行工具"""
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            logger.error(f"Tool '{name}' not found")
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.list_tools())}"

        try:
            logger.debug(f"Executing tool: {name}")

            params = tool.cast_params(params)

            errors = tool.validate_params(params)
            if errors:
                logger.warning(f"Tool {name} validation failed: {'; '.join(errors)}")
                return f"Error: Invalid parameters: {'; '.join(errors)}{_HINT}"

            result = await tool.execute(**params)

            if isinstance(result, str) and result.startswith("Error:"):
                return result + _HINT

            # 结构化：dict/list → JSON 字符串
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False)

            return result

        except Exception as e:
            logger.error(f"Tool execution failed: {name} - {e}")
            return f"Error executing {name}: {str(e)}{_HINT}"

    async def execute_batch(self, tool_calls: List[Dict[str, Any]]) -> List[Any]:
        """并发执行多个工具调用"""
        tasks = [
            self.execute(call["name"], call["arguments"])
            for call in tool_calls
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = []
        for result in results:
            if isinstance(result, Exception):
                processed.append(f"Error: {type(result).__name__}: {result}")
            else:
                processed.append(result)

        return processed

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
