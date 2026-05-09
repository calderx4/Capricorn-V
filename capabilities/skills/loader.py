"""
Skill Loader - 技能加载器

职责：
- 加载 SKILL.md 文件
- 解析 YAML frontmatter
- 提供技能摘要
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger


class SkillLoader:
    """技能加载器"""

    @staticmethod
    def load(skill_path: Path) -> Dict[str, Any]:
        """
        加载 SKILL.md 文件

        Args:
            skill_path: SKILL.md 文件路径

        Returns:
            技能信息字典，包含：
            - name: 技能名称
            - description: 技能描述
            - capabilities: 依赖的能力列表
            - always: 是否总是加载
            - content: 技能详细内容

        Raises:
            FileNotFoundError: 文件不存在
        """
        if not skill_path.exists():
            raise FileNotFoundError(f"Skill file not found: {skill_path}")

        content = skill_path.read_text(encoding="utf-8")

        # 解析 YAML frontmatter
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1])
                    body = parts[2].strip()

                    return {
                        "name": frontmatter.get("name"),
                        "description": frontmatter.get("description", ""),
                        "available": frontmatter.get("available", False),
                        "content": body,
                        "path": str(skill_path)
                    }
                except yaml.YAMLError as e:
                    logger.warning(f"Failed to parse frontmatter in {skill_path}: {e}")

        # 无 frontmatter，返回纯内容
        return {
            "name": skill_path.parent.name,
            "description": "",
            "available": False,
            "content": content,
            "path": str(skill_path)
        }

    @staticmethod
    def get_summary(skill_data: Dict[str, Any]) -> str:
        name = skill_data.get("name", "unknown")
        description = skill_data.get("description", "")
        return f'<skill name="{name}">\n  <description>{description}</description>\n</skill>'

    @staticmethod
    def find_skill_file(skill_dir: Path) -> Optional[Path]:
        """
        在技能目录中查找 SKILL.md 文件

        Args:
            skill_dir: 技能目录

        Returns:
            SKILL.md 文件路径，如果不存在返回 None
        """
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            return skill_file

        # 尝试小写
        skill_file = skill_dir / "skill.md"
        if skill_file.exists():
            return skill_file

        return None
