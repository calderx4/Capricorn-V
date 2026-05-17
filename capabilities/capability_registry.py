"""
Capability Registry - 能力注册中心

职责：
- 统一管理 Tool（builtin / mcp / workflow / vertical）
- 提供 create 工厂方法
- 支持从任意目录动态注册 tools 和 workflows
- 协调执行
"""

import importlib.util
import inspect
import json
from typing import Dict, Any, Generator
from loguru import logger

from pathlib import Path

from capabilities.tools.registry import ToolRegistry
from config.settings import MCPServerConfig
from core.base_tool import BaseTool
from core.base_workflow import BaseWorkflow


class CapabilityRegistry:
    """能力注册中心 - 统一管理所有 Tool（builtin / mcp / workflow / vertical）"""

    def __init__(self):
        self.tools = ToolRegistry()
        self._mcp_manager = None

    @classmethod
    async def create(cls, workspace_root: str = "./workspace", sandbox: bool = True, skill_manager=None, blocked_commands: list = None) -> "CapabilityRegistry":
        registry = cls()
        registry._workspace_root = workspace_root
        registry._sandbox = sandbox
        registry._skill_manager = skill_manager
        registry._blocked_commands = blocked_commands or []

        logger.info(f"CapabilityRegistry initialized (tools will be loaded via VerticalLoader)")
        return registry

    def _discover(self, directory, base_class: type, config: dict = None) -> Generator[Any, None, None]:
        """扫描目录，自动发现并实例化基类子类"""
        ext_dir = Path(directory) if Path(directory).is_absolute() else Path(directory)
        if not ext_dir.exists():
            return

        for py_file in sorted(ext_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue

            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as e:
                logger.error(f"Failed to import {py_file}: {e}")
                continue

            for _, cls in inspect.getmembers(module, inspect.isclass):
                if (issubclass(cls, base_class)
                        and cls is not base_class
                        and cls.__module__ == module.__name__
                        and getattr(cls, "auto_discover", True)):
                    try:
                        yield cls.from_config(config or {})
                    except Exception as e:
                        logger.error(f"Failed to instantiate {cls.__name__}: {e}")

    async def register_tools_from_dir(self, tools_dir: Path, config: dict, layer: str = "vertical", vertical_name: str = None):
        """从指定目录扫描并注册 tools。工具使用原始名称，无前缀。"""
        for tool in self._discover(tools_dir, BaseTool, config):
            self.tools.register(tool, layer=layer, vertical_name=vertical_name)
            logger.debug(f"Registered [{layer}] tool: {tool.name}")

    async def register_workflows_from_dir(self, workflows_dir: Path, layer: str = "vertical"):
        """从指定目录扫描并注册 workflows"""
        from capabilities.tools.workflow.workflow_wrapper import WorkflowToolWrapper

        for wf in self._discover(workflows_dir, BaseWorkflow):
            wrapper = WorkflowToolWrapper(wf, self.tools)
            self.tools.register(wrapper, layer=layer)
            logger.debug(f"Registered [{layer}] workflow: {wf.name}")

    async def register_mcp_from_config(self, mcp_config_path: Path):
        """从 JSON 配置文件加载 MCP servers"""
        if not mcp_config_path.exists():
            return

        with open(mcp_config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        from config.settings import Config
        raw = Config._resolve_env_vars(raw)

        mcp_servers = {name: MCPServerConfig(**cfg) for name, cfg in raw.items()}
        await self._register_mcp_tools(mcp_servers)

    async def _register_mcp_tools(self, mcp_servers: Dict[str, Any]):
        from capabilities.tools.mcp.mcp_client import MCPClientManager

        self._mcp_manager = MCPClientManager(mcp_servers)
        await self._mcp_manager.connect(self.tools, layer="mcp")

    async def register_skill_tools(self, skill_manager, vertical_dir: Path = None):
        """注册 skill_view 工具"""
        import importlib.util
        project_root = Path(__file__).parent.parent
        if vertical_dir:
            skill_tool_path = vertical_dir / "tools" / "skill_tool.py"
        else:
            skill_tool_path = project_root / "vertical_hub" / "default" / "tools" / "skill_tool.py"
        if not skill_tool_path.exists():
            logger.warning("skill_tool.py not found, skipping skill_view registration")
            return

        spec = importlib.util.spec_from_file_location("skill_tool", skill_tool_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        SkillViewTool = module.SkillViewTool

        if skill_manager.get_available_skills():
            tool = SkillViewTool(skill_manager)
            self.tools.register(tool, layer="builtin")

    def unregister_by_vertical(self, vertical_name: str):
        """注销某个垂类的所有 tools"""
        self.tools.unregister_by_vertical(vertical_name)

    async def execute_tool(self, name: str, params: Dict[str, Any]) -> Any:
        return await self.tools.execute(name, params)

    def get_langchain_tools(self) -> list:
        return self.tools.get_langchain_tools()

    async def cleanup(self):
        if self._mcp_manager:
            await self._mcp_manager.disconnect()
        logger.debug("CapabilityRegistry cleanup completed")
