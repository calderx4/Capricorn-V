"""
VerticalLoader - 垂类加载器

职责：
- 读取 manifest.yaml + vertical.yaml
- 按垂类加载 tools / MCP / skills / workflows / prompts
- 管理已加载垂类的生命周期
"""

from pathlib import Path
from typing import Dict, Any, Optional

import yaml
from loguru import logger


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
        p = (vertical_dir / rel_path).resolve()
        vertical_root = vertical_dir.resolve()
        if not str(p).startswith(str(vertical_root)):
            raise ValueError(f"Path traversal detected: '{rel_path}' resolves outside vertical directory")
        return p

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
                await capability_registry.register_tools_from_dir(
                    tools_dir, config_dict, layer="vertical", vertical_name=name,
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

        # 6. 加载 roles
        roles_rel = manifest.get("roles")
        if roles_rel:
            roles_dir = self._resolve_path(vertical_dir, roles_rel)
            if roles_dir.exists():
                roles = self._load_roles(roles_dir, vertical_dir)
                if roles:
                    result["roles"] = roles
                    logger.info(f"Vertical '{name}': roles loaded: {list(roles.keys())}")

        self._loaded[name] = result
        logger.info(f"✓ Vertical '{name}' loaded successfully")
        return result

    def _load_roles(self, roles_dir: Path, vertical_dir: Path) -> Dict[str, dict]:
        """扫描 roles/ 目录，加载角色定义"""
        roles = {}
        for yaml_file in sorted(roles_dir.glob("*.yaml")):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    role_def = yaml.safe_load(f)

                role_name = role_def.get("name", yaml_file.stem)
                prompt_rel = role_def.get("prompt")
                prompt_path = str(self._resolve_path(vertical_dir, prompt_rel)) if prompt_rel else None

                roles[role_name] = {
                    "name": role_name,
                    "description": role_def.get("description", ""),
                    "prompt_path": prompt_path,
                    "tools": role_def.get("tools", "all"),
                }
            except Exception as e:
                logger.error(f"Failed to load role {yaml_file}: {e}")

        return roles
