"""
VerticalLoader - 垂类加载器

职责：
- 读取 manifest.yaml + vertical.yaml
- 按垂类加载 tools / MCP / skills / workflows / prompts
- 管理已加载垂类的生命周期
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional

import yaml
from loguru import logger

from config.settings import Config, MCPServerConfig


class VerticalLoader:
    """垂类加载器 — 一键加载一个垂直领域的全部能力"""

    def __init__(self, hub_root: str, project_root: str):
        self.hub_root = Path(hub_root)
        self.project_root = Path(project_root).resolve()
        self._loaded: Dict[str, dict] = {}
        self._manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        manifest_path = self.hub_root / "manifest.yaml"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Vertical manifest not found: {manifest_path}")
        with open(manifest_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _resolve_path(self, vertical_dir: Path, rel_path: str) -> Path:
        """将 vertical.yaml 中的相对路径解析为绝对路径"""
        p = vertical_dir / rel_path
        return p.resolve()

    def list_available(self) -> list[str]:
        return [v["name"] for v in self._manifest.get("verticals", [])]

    def is_loaded(self, name: str) -> bool:
        return name in self._loaded

    def get_vertical_dir(self, name: str) -> Optional[Path]:
        for v in self._manifest.get("verticals", []):
            if v["name"] == name:
                return (self.hub_root / v["path"]).resolve()
        return None

    async def load(
        self,
        name: str,
        capability_registry,
        skill_manager,
        config: dict = None,
    ) -> dict:
        if self.is_loaded(name):
            logger.warning(f"Vertical '{name}' already loaded, skipping")
            return self._loaded[name]

        vertical_dir = self.get_vertical_dir(name)
        if not vertical_dir:
            raise ValueError(f"Vertical '{name}' not found in manifest")

        vertical_yaml_path = vertical_dir / "vertical.yaml"
        if not vertical_yaml_path.exists():
            raise FileNotFoundError(f"vertical.yaml not found: {vertical_yaml_path}")

        with open(vertical_yaml_path, "r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

        result: Dict[str, Any] = {
            "name": name,
            "manifest": manifest,
            "vertical_dir": str(vertical_dir),
        }

        # 1. 加载 tools
        tools_rel = manifest.get("tools")
        if tools_rel:
            tools_dir = self._resolve_path(vertical_dir, tools_rel)
            if tools_dir.exists():
                config_dict = config or {
                    "workspace_root": getattr(capability_registry, "_workspace_root", "./workspace"),
                    "sandbox": getattr(capability_registry, "_sandbox", True),
                    "blocked_commands": getattr(capability_registry, "_blocked_commands", []),
                }
                # tool_prefix 控制：yaml 里显式声明才生效
                #   tool_prefix: false / "" → 不加前缀
                #   tool_prefix: "xxx"     → 用 xxx 作前缀
                #   不声明                  → 走原逻辑（default 不加，其余加 vertical_name_）
                register_name = None
                if "tool_prefix" in manifest:
                    tp = manifest["tool_prefix"]
                    if tp is False or tp == "":
                        register_name = ""
                    else:
                        register_name = str(tp)
                await capability_registry.register_tools_from_dir(
                    tools_dir, config_dict, layer="vertical", vertical_name=name,
                    tool_prefix=register_name,
                )
                logger.info(f"Vertical '{name}': tools loaded from {tools_dir}")

        # 2. 加载 MCP
        mcp_rel = manifest.get("mcp_servers")
        if mcp_rel:
            mcp_path = self._resolve_path(vertical_dir, mcp_rel)
            if mcp_path.exists():
                await capability_registry.register_mcp_from_config(mcp_path)
                result["mcp_config_path"] = str(mcp_path)
                logger.info(f"Vertical '{name}': MCP loaded from {mcp_path}")

        # 3. 加载 skills
        skills_rel = manifest.get("skills")
        if skills_rel:
            skills_dir = self._resolve_path(vertical_dir, skills_rel)
            if skills_dir.exists():
                skill_manager.add_skills_dir(name, skills_dir)
                logger.info(f"Vertical '{name}': skills loaded from {skills_dir}")

        # 4. 加载 workflows
        workflows_rel = manifest.get("workflows")
        if workflows_rel:
            workflows_dir = self._resolve_path(vertical_dir, workflows_rel)
            if workflows_dir.exists():
                await capability_registry.register_workflows_from_dir(workflows_dir, layer="vertical")
                logger.info(f"Vertical '{name}': workflows loaded from {workflows_dir}")

        # 5. 加载 prompts
        prompt_rel = manifest.get("prompt")
        if prompt_rel:
            prompt_dir = self._resolve_path(vertical_dir, prompt_rel)
            if prompt_dir.exists():
                system_md = prompt_dir / "system.md"
                if system_md.exists():
                    result["system_prompt_path"] = str(system_md)

                cron_md = prompt_dir / "cron.md"
                if cron_md.exists():
                    result["cron_prompt_path"] = str(cron_md)

                logger.info(f"Vertical '{name}': prompts loaded from {prompt_dir}")

        self._loaded[name] = result
        logger.info(f"✓ Vertical '{name}' loaded successfully")
        return result

    async def unload(self, name: str, capability_registry, skill_manager):
        if not self.is_loaded(name):
            return

        capability_registry.unregister_by_vertical(name)
        skill_manager.remove_skills_by_vertical(name)
        self._loaded.pop(name, None)
        logger.info(f"✓ Vertical '{name}' unloaded")
