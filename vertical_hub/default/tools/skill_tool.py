"""
SkillViewTool - 技能查看工具

职责：
- 允许 LLM 按需加载技能的完整内容
"""

from typing import Any, Dict
from loguru import logger

from core.base_tool import BaseTool


class SkillViewTool(BaseTool):
    """技能查看工具 - LLM 通过此工具获取技能的完整指令"""

    auto_discover = False  # 由 _register_skill_tools 手动注册，不走自动发现

    def __init__(self, skill_manager):
        self._skill_manager = skill_manager

    @property
    def name(self) -> str:
        return "skill_view"

    @property
    def description(self) -> str:
        available = self._skill_manager.get_available_skills()
        if not available:
            return "No skills available."

        # 只展示无命名空间的简洁名（default 垂类的 skills 同时保留两种 key）
        display_names = [k for k in available.keys() if "." not in k]
        if not display_names:
            display_names = list(available.keys())
        names = ", ".join(sorted(display_names))
        return (
            "按需加载技能（Skill）的完整指令。技能是针对特定领域（前端开发、文档生成等）的专业化指导包。\n"
            "触发场景：用户请求匹配某个技能领域时，必须先调用此工具加载完整指令后再执行任务。\n"
            f"可用技能: {names}"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要加载的技能名称",
                },
            },
            "required": ["name"],
        }

    async def execute(self, **kwargs: Any) -> Any:
        skill_name = kwargs.get("name", "").strip()

        if not skill_name:
            return "Error: skill name is required"

        content = self._skill_manager.load_skill(skill_name)
        if content.startswith("Error:"):
            return content

        logger.info(f"Skill loaded: {skill_name}")

        return content
