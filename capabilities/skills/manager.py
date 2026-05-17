"""
Skill Manager - 技能管理器

职责：
- 管理所有技能
- 生成技能摘要（XML 格式）
- 按需加载技能详情
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger

from .loader import SkillLoader


class SkillManager:
    """技能管理器"""

    def __init__(self):
        self._skills: Dict[str, Dict[str, Any]] = {}
        self._vertical_dirs: Dict[str, Path] = {}  # vertical_name → skills_dir

    def add_skills_dir(self, vertical_name: str, skills_dir) -> None:
        """按垂类命名空间追加 skill 目录"""
        dir_path = Path(skills_dir)
        if not dir_path.exists():
            return

        self._vertical_dirs[vertical_name] = dir_path

        for skill_dir in dir_path.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_file = SkillLoader.find_skill_file(skill_dir)
            if not skill_file:
                continue

            try:
                skill_data = SkillLoader.load(skill_file)
                skill_name = skill_data.get("name")
                if not skill_name:
                    logger.warning(f"Skill missing 'name' field: {skill_file}")
                    continue

                namespaced = f"{vertical_name}.{skill_name}"
                self._skills[namespaced] = skill_data

                # default 垂类同时保留无前缀版本，保持向后兼容
                if vertical_name == "default":
                    self._skills[skill_name] = skill_data

                logger.debug(f"Loaded skill: {namespaced}")
            except Exception as e:
                logger.error(f"Failed to load skill from {skill_file}: {e}")

    def remove_skills_by_vertical(self, vertical_name: str) -> None:
        """按垂类移除 skills"""
        prefix = f"{vertical_name}."
        to_remove = [k for k in self._skills if k.startswith(prefix)]
        for k in to_remove:
            self._skills.pop(k, None)
        self._vertical_dirs.pop(vertical_name, None)

    def list_skills(self) -> List[str]:
        """
        列出所有技能名称

        Returns:
            技能名称列表
        """
        return list(self._skills.keys())

    def get_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """
        获取技能详情

        Args:
            name: 技能名称

        Returns:
            技能数据字典，不存在返回 None
        """
        return self._skills.get(name)

    def load_skill(self, name: str) -> str:
        """
        加载完整技能内容

        Args:
            name: 技能名称

        Returns:
            技能详细内容
        """
        skill_data = self._skills.get(name)
        if not skill_data:
            return f"Error: Skill '{name}' not found"

        return skill_data.get("content", "")

    def get_available_skills(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有 available=true 的技能（即告诉模型可用的技能）

        Returns:
            可用技能字典 {name: skill_data}
        """
        return {
            name: data for name, data in self._skills.items()
            if data.get("available", False)
        }

    def get_autoload_skills(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有 autoload=true 的技能，用于直接注入 system prompt。

        Returns:
            自动加载技能字典 {name: skill_data}
        """
        seen = set()
        result = {}
        for name, data in self._skills.items():
            if data.get("autoload", False):
                # 无命名空间优先（避免 default.xxx 重复）
                short_name = name.split(".", 1)[-1] if "." in name else name
                if short_name not in seen:
                    seen.add(short_name)
                    result[short_name] = data
        return result

    def get_skill_summary(self) -> str:
        """
        获取所有可用技能的摘要（XML 格式）

        Returns:
            XML 格式的技能摘要
        """
        available = self.get_available_skills()

        if not available:
            return ""

        summaries = []
        for skill_name, skill_data in available.items():
            summary = SkillLoader.get_summary(skill_data)
            summaries.append(summary)

        return "<skills>\n" + "\n".join(summaries) + "\n</skills>"
