"""
Todo Tools - 任务规划与跟踪

让 agent 在处理复杂多步任务时能规划和跟踪进度。
"""

import json
from pathlib import Path
from typing import Any, Dict
from loguru import logger

from core.base_tool import BaseTool
from core.utils import atomic_write

_STATUS_ICONS = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}


class TodoTool(BaseTool):
    """任务规划与跟踪工具"""

    def __init__(self, workspace_root: str = "./workspace"):
        self._todo_path = Path(workspace_root) / ".todo.json"

    @classmethod
    def from_config(cls, config: dict) -> "TodoTool":
        return cls(config["workspace_root"])

    @property
    def name(self) -> str:
        return "todo"

    @property
    def description(self) -> str:
        return (
            "任务规划与进度跟踪工具，适用于复杂多步任务。\n"
            "用法：\n"
            "  add — 添加任务（content 必填），返回新任务 ID\n"
            "  list — 查看所有任务及状态（[ ]未开始 / [~]进行中 / [x]已完成）\n"
            "  update — 更新任务状态（task_id + status 必填）\n"
            "  get — 查看单个任务详情（task_id 必填）\n"
            "  delete — 删除任务（task_id 必填）\n"
            "  clear — 清空任务列表\n"
            "建议：复杂任务先 add 规划步骤，逐步执行时每步 update in_progress，完成后 update completed。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "update", "list", "get", "delete", "clear"],
                    "description": "操作类型",
                },
                "content": {
                    "type": "string",
                    "description": "任务描述（add 时必填）",
                },
                "task_id": {
                    "type": "integer",
                    "description": "任务 ID（update/get/delete 时必填）",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"],
                    "description": "任务状态（update 时必填）",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, content: str = None, task_id: int = None, status: str = None) -> str:
        try:
            todos = self._load()

            if action == "add":
                if not content:
                    return "Error: 添加任务需要提供 content"
                new_id = max((t["id"] for t in todos), default=0) + 1
                todos.append({"id": new_id, "content": content, "status": "pending"})
                self._save(todos)
                return f"已添加任务 #{new_id}: {content}"

            elif action == "update":
                if task_id is None or not status:
                    return "Error: 更新任务需要提供 task_id 和 status"
                for t in todos:
                    if t["id"] == task_id:
                        t["status"] = status
                        self._save(todos)
                        return f"任务 #{task_id} 状态更新为 {status}"
                return f"Error: 未找到任务 #{task_id}"

            elif action == "list":
                if not todos:
                    return "任务列表为空"
                lines = []
                for t in todos:
                    icon = _STATUS_ICONS[t["status"]]
                    lines.append(f"  #{t['id']} {icon} {t['content']}")
                return "任务列表：\n" + "\n".join(lines)

            elif action == "get":
                if task_id is None:
                    return "Error: get 需要提供 task_id"
                for t in todos:
                    if t["id"] == task_id:
                        icon = _STATUS_ICONS[t["status"]]
                        return f"#{t['id']} {icon} {t['content']}"
                return f"Error: 未找到任务 #{task_id}"

            elif action == "delete":
                if task_id is None:
                    return "Error: delete 需要提供 task_id"
                new_todos = [t for t in todos if t["id"] != task_id]
                if len(new_todos) == len(todos):
                    return f"Error: 未找到任务 #{task_id}"
                self._save(new_todos)
                return f"已删除任务 #{task_id}"

            elif action == "clear":
                self._save([])
                return "已清空任务列表"

            return f"Error: 未知 action '{action}'"

        except Exception as e:
            logger.error(f"todo tool failed: {e}")
            return f"Error: {e}"

    def _load(self) -> list:
        if not self._todo_path.exists():
            return []
        try:
            return json.loads(self._todo_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, todos: list):
        self._todo_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            self._todo_path,
            json.dumps(todos, ensure_ascii=False, indent=2),
        )
