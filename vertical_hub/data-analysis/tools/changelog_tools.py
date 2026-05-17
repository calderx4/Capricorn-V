"""
Changelog Tools — 变更日志工具

自进化基础设施的一部分，记录和查询系统自改动历史。
格式遵循 docs/探讨自进化/落地步骤/02-core-infrastructure.md §2。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from core.base_tool import BaseTool
from core.utils import atomic_write


class ChangelogTool(BaseTool):
    """变更日志读写"""

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True):
        self._workspace_root = workspace_root
        self._sandbox = sandbox

    @classmethod
    def from_config(cls, config: dict) -> "ChangelogTool":
        return cls(config["workspace_root"], config.get("sandbox", True))

    @property
    def name(self) -> str:
        return "changelog"

    @property
    def description(self) -> str:
        return (
            "记录或查询变更日志。action=add 时记录一条变更，action=list 时查询最近的变更，"
            "action=update_status 时更新某条变更的状态（如确认/回滚）。\n"
            "变更类型：bia | skill | workflow | tool\n"
            "变更状态：applied | pending_approval | confirmed | rolled_back"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "update_status"],
                    "description": "add=记录变更，list=查询列表，update_status=更新状态",
                },
                "type": {
                    "type": "string",
                    "enum": ["bia", "skill", "workflow", "tool"],
                    "description": "变更类型（add 时必填）",
                },
                "target": {
                    "type": "string",
                    "description": "改了什么文件（add 时必填）",
                },
                "content": {
                    "type": "string",
                    "description": "变更内容描述（add 时必填）",
                },
                "reason": {
                    "type": "string",
                    "description": "变更原因（add 时必填）",
                },
                "trigger": {
                    "type": "string",
                    "enum": ["verifier_cron", "human_feedback"],
                    "description": "触发来源（默认 verifier_cron）",
                },
                "status": {
                    "type": "string",
                    "enum": ["applied", "pending_approval", "confirmed", "rolled_back"],
                    "description": "变更状态（add 时默认 applied，update_status 时为要设的新状态）",
                },
                "entry_id": {
                    "type": "string",
                    "description": "要更新状态的条目 ID（update_status 时必填）",
                },
                "limit": {
                    "type": "integer",
                    "description": "查询数量限制（list 时使用，默认 20）",
                },
                "since": {
                    "type": "string",
                    "description": "查询起始日期，格式 YYYY-MM-DD（list 时可选）",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        type: str = None,
        target: str = None,
        content: str = None,
        reason: str = None,
        trigger: str = "verifier_cron",
        status: str = None,
        entry_id: str = None,
        limit: int = 20,
        since: str = None,
    ) -> str:
        try:
            changelog_dir = Path(self._workspace_root) / "team" / "changelog"
            changelog_dir.mkdir(parents=True, exist_ok=True)

            if action == "add":
                if not all([type, target, content, reason]):
                    return "Error: type, target, content, reason are required for add"
                entry_status = status or "applied"
                entry = {
                    "id": datetime.now().strftime("%Y%m%d%H%M%S"),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "type": type,
                    "action": "add",
                    "target": target,
                    "content": content,
                    "reason": reason,
                    "trigger": trigger,
                    "status": entry_status,
                }
                day_file = changelog_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
                with open(day_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                logger.info(f"Changelog entry: [{type}] {content[:50]}")
                return json.dumps(entry, ensure_ascii=False, indent=2)

            elif action == "list":
                entries = self._read_entries(changelog_dir, limit, since)
                return json.dumps(entries, ensure_ascii=False, indent=2)

            elif action == "update_status":
                if not entry_id or not status:
                    return "Error: entry_id and status are required for update_status"
                updated = self._update_entry_status(changelog_dir, entry_id, status)
                if updated:
                    return f"Status updated: {entry_id} -> {status}"
                return f"Error: entry {entry_id} not found"

            return f"Error: unknown action '{action}'"

        except Exception as e:
            logger.error(f"changelog failed: {e}")
            return f"Error: {e}"

    def _read_entries(
        self, changelog_dir: Path, limit: int, since: str = None
    ) -> List[dict]:
        """读取变更日志条目，按时间倒序。"""
        files = sorted(changelog_dir.glob("*.jsonl"), reverse=True)
        entries = []
        for f in files:
            if since and f.stem < since:
                continue
            for line in f.read_text(encoding="utf-8").strip().split("\n"):
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            if len(entries) >= limit:
                break
        return entries[:limit]

    def _update_entry_status(
        self, changelog_dir: Path, entry_id: str, new_status: str
    ) -> bool:
        """更新指定条目的状态。"""
        for f in changelog_dir.glob("*.jsonl"):
            lines = f.read_text(encoding="utf-8").strip().split("\n")
            updated = False
            new_lines = []
            for line in lines:
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    new_lines.append(line)
                    continue
                if entry.get("id") == entry_id:
                    entry["status"] = new_status
                    updated = True
                new_lines.append(json.dumps(entry, ensure_ascii=False))
            if updated:
                atomic_write(f, "\n".join(new_lines) + "\n")
                return True
        return False
