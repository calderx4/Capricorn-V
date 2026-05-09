"""
Memory Tools - 记忆操作工具

让 LLM 主动更新长期记忆和搜索历史记录。
"""

from typing import Any, Dict, List
from loguru import logger

from core.base_tool import BaseTool
from memory.long_term import LongTermMemory
from memory.history import HistoryLog
from config.settings import WorkspaceConfig


class MemoryUpdateTool(BaseTool):
    """主动更新长期记忆工具"""

    def __init__(self, workspace_root: str = "./workspace"):
        ws_config = WorkspaceConfig(root=workspace_root)
        self._memory = LongTermMemory(ws_config)

    @classmethod
    def from_config(cls, config: dict) -> "MemoryUpdateTool":
        return cls(config["workspace_root"])

    @property
    def name(self) -> str:
        return "memory_update"

    @property
    def description(self) -> str:
        return (
            "主动更新长期记忆（MEMORY.md）。适用场景：记住用户偏好、项目事实、重要决策。\n"
            "mode=append 时追加内容，mode=replace 时替换全部内容。默认 append。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要记住的内容（Markdown 格式）",
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
            if mode == "replace":
                self._memory.write(content)
                return f"已替换长期记忆（{len(content)} 字符）"
            else:
                self._memory.append(content)
                return f"已追加到长期记忆（{len(content)} 字符）"
        except Exception as e:
            logger.error(f"memory_update failed: {e}")
            return f"Error: {e}"


class HistorySearchTool(BaseTool):
    """搜索历史记录工具"""

    def __init__(self, workspace_root: str = "./workspace"):
        ws_config = WorkspaceConfig(root=workspace_root)
        self._history = HistoryLog(ws_config)

    @classmethod
    def from_config(cls, config: dict) -> "HistorySearchTool":
        return cls(config["workspace_root"])

    @property
    def name(self) -> str:
        return "history_search"

    @property
    def description(self) -> str:
        return (
            "搜索历史对话记录（HISTORY.md）。适用场景：找过去的对话、用户偏好、任务记录。\n"
            "参数：query（关键词）、since/until（时间范围 YYYY-MM-DD）、limit（返回条数上限，默认5）。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                },
                "since": {
                    "type": "string",
                    "description": "起始日期，格式 YYYY-MM-DD（可选）",
                },
                "until": {
                    "type": "string",
                    "description": "截止日期，格式 YYYY-MM-DD（可选）",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数上限，默认 5",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, since: str = None, until: str = None, limit: int = 5) -> str:
        try:
            # 用 HistoryLog.search() 做关键词匹配
            matched = self._history.search(query)
            if not matched:
                return f"未找到包含 '{query}' 的历史记录"

            # 时间过滤
            if since or until:
                matched = self._filter_by_time(matched, since, until)
                if not matched:
                    return f"在指定时间范围内未找到包含 '{query}' 的历史记录"

            results = matched[:limit]
            output = [f"找到 {len(matched)} 条记录（显示前 {len(results)} 条）：\n"]
            for i, entry in enumerate(results, 1):
                output.append(f"{i}. {entry}")

            return "\n".join(output)

        except Exception as e:
            logger.error(f"history_search failed: {e}")
            return f"Error: {e}"

    def _filter_by_time(self, entries: List[str], since: str = None, until: str = None) -> List[str]:
        """按时间范围过滤历史条目"""
        import re

        def extract_date(entry: str) -> str:
            # 匹配 [YYYY-MM-DD ...] 格式
            m = re.match(r'\[(\d{4}-\d{2}-\d{2})', entry)
            return m.group(1) if m else ""

        filtered = []
        for entry in entries:
            date = extract_date(entry)
            if not date:
                continue
            if since and date < since:
                continue
            if until and date > until:
                continue
            filtered.append(entry)

        return filtered
