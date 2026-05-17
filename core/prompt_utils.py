"""
Prompt 工具函数 — PromptBuilder + section 构建器

供 agent.py 和 scheduler.py 共用，避免重复逻辑。
"""

from pathlib import Path
from loguru import logger

from capabilities.skills.loader import SkillLoader


class PromptBuilder:
    """Prompt 组装器 — 注册 section → 替换模板 → 输出"""

    def __init__(self, template_path: str):
        p = Path(template_path)
        if not p.exists():
            raise FileNotFoundError(f"Prompt template not found: {template_path}")
        self.template_path = template_path
        self._sections: dict[str, str] = {}

    def set(self, name: str, content: str):
        self._sections[name] = content

    def build(self) -> str:
        template = Path(self.template_path).read_text("utf-8")
        for name, content in self._sections.items():
            template = template.replace("{{" + name + "}}", content)
        return clean_empty_sections(template)

LAYER_DESC_MAP = {
    "builtin": "## Built-in Tools\n本地基础能力 — 文件操作、命令执行、任务规划、记忆管理。",
    "mcp": "## MCP Tools\n外部服务集成（地图、交通等），按需调用。",
    "workflow": "## Workflow Tools\n复杂多步编排任务，调用多个工具协作完成。",
    "vertical": "## Vertical Tools\n垂直领域专属工具，按需加载。",
}


def build_tools_section(capability_registry) -> str:
    if not capability_registry:
        return ""
    tool_registry = capability_registry.tools
    if not hasattr(tool_registry, "list_by_layer"):
        return ""
    layers = tool_registry.list_by_layer()
    if not any(layers.values()):
        return ""
    sections = []
    for layer_name, tools in layers.items():
        if not tools:
            continue
        desc = LAYER_DESC_MAP.get(layer_name, f"## {layer_name}")
        details = []
        for name in tools:
            tool = tool_registry.get(name)
            details.append(f"- **{name}**: {tool.description if tool else ''}")
        sections.append(f"{desc}\n\n" + "\n".join(details))
    return "# Available Tools\n\n" + "\n\n".join(sections)


def build_skills_section(skill_manager) -> str:
    if not skill_manager or not hasattr(skill_manager, "list_skills"):
        return ""
    skills = skill_manager.list_skills()
    if not skills:
        return ""

    parts = []

    # 1. autoload 技能：内容直接注入 system prompt
    autoload_skills = skill_manager.get_autoload_skills()
    if autoload_skills:
        for skill_name, skill_data in autoload_skills.items():
            content = skill_data.get("content", "").strip()
            if content:
                parts.append(f"# Skill: {skill_name}\n\n{content}")

    # 2. available 但非 autoload 的技能：只注入摘要，按需 skill_view 加载
    available = skill_manager.get_available_skills()
    on_demand = {
        k: v for k, v in available.items()
        if not v.get("autoload", False) and "." not in k
    }
    if on_demand:
        summaries = [SkillLoader.get_summary(v) for v in on_demand.values()]
        summary = "<skills>\n" + "\n".join(summaries) + "\n</skills>"

        if summary:
            parts.append(
                "# Available Skills\n\n"
                "你可以使用以下技能。当用户的请求匹配某个技能时，"
                "**必须**先调用 `skill_view(name)` 加载完整指令后再执行。\n\n"
                f"{summary}"
            )

    return "\n\n".join(parts)


def build_memory_section(long_term_memory) -> str:
    if not long_term_memory:
        return ""
    content = long_term_memory.read()
    if not content:
        return ""
    return (
        "# Long-term Memory\n\n"
        "以下包含需要始终记住的重要事实、偏好和上下文。\n\n"
        f"{content}"
    )


def build_bia_section(bia_path: str) -> str:
    if not bia_path:
        return ""
    p = Path(bia_path)
    if not p.exists():
        return ""
    content = p.read_text(encoding="utf-8").strip()
    if not content:
        return ""
    return (
        "# Behavioral Corrections\n\n"
        "以下行为纠偏规则在执行任务时持续生效。"
        "你可以通过 bia_update 工具更新这些规则。\n\n"
        f"{content}"
    )


def clean_empty_sections(text: str) -> str:
    """清理模板替换后残留的连续空行"""
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()
