"""
Bia Tools — 行为纠偏规则工具

让 LLM 主动更新 bia.md（行为纠偏规则），用于自进化中环。
"""

from typing import Any, Dict
from loguru import logger
from pathlib import Path

from core.base_tool import BaseTool
from core.utils import atomic_write


class BiaUpdateTool(BaseTool):
    """更新行为纠偏规则"""

    auto_discover = False

    def __init__(self, bia_path: str):
        self._bia_path = Path(bia_path)

    @property
    def name(self) -> str:
        return "bia_update"

    @property
    def description(self) -> str:
        return (
            "更新行为纠偏规则（bia.md）。适用场景：发现自己在某些模式下反复犯错，"
            "需要添加持久的行为修正规则。"
            "每次仅允许修改一条规则。\n"
            "mode=append 时追加规则，mode=replace 时替换全部规则。默认 append。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要添加的行为修正规则（Markdown 格式）",
                },
                "mode": {
                    "type": "string",
                    "enum": ["append", "replace"],
                    "description": "append=追加，replace=替换全部。默认 append。",
                    "default": "append",
                },
            },
            "required": ["content"],
        }

    async def execute(self, content: str, mode: str = "append") -> str:
        try:
            self._bia_path.parent.mkdir(parents=True, exist_ok=True)
            if mode == "replace":
                atomic_write(self._bia_path, content)
                return f"已替换行为纠偏规则（{len(content)} 字符）"
            else:
                with open(self._bia_path, "a", encoding="utf-8") as f:
                    f.write(content + "\n")
                return f"已追加行为纠偏规则（{len(content)} 字符）"
        except Exception as e:
            logger.error(f"bia_update failed: {e}")
            return f"Error: {e}"
