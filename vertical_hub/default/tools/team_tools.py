"""
Team Tools - SubAgent 任务管理工具

职责：
- TaskManageTool：管理任务状态机（create / list / update / get）
- SpawnTool：召唤 SubAgent（executor / verifier）执行子任务
"""

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from loguru import logger

from core.base_tool import BaseTool
from core.utils import atomic_write

_TASK_ID_RE = re.compile(r'^task_[a-f0-9]{8}$')


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class TaskManageTool(BaseTool):
    """管理任务状态机"""

    name = "task"
    description = "管理团队任务状态机：创建、查询、更新任务状态（producing → verifying → done/failed）"
    auto_discover = False

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "update", "get"],
                    "description": "操作类型",
                },
                "task_id": {
                    "type": "string",
                    "description": "任务 ID（update / get 时必填）",
                },
                "title": {
                    "type": "string",
                    "description": "任务标题（create 时必填）",
                },
                "description": {
                    "type": "string",
                    "description": "任务描述（create 时可选）",
                },
                "status": {
                    "type": "string",
                    "enum": ["producing", "verifying", "done", "failed"],
                    "description": "目标状态（update 时必填）",
                },
                "assigned_role": {
                    "type": "string",
                    "enum": ["executor", "verifier"],
                    "description": "分配角色（create 时可选，默认 executor）",
                },
                "max_attempts": {
                    "type": "integer",
                    "description": "最大重试次数（create 时可选，默认 3）",
                },
                "filter_status": {
                    "type": "string",
                    "description": "按状态筛选（list 时可选）",
                },
            },
            "required": ["action"],
        }

    def __init__(self, workspace_root: str):
        self._workspace_root = Path(workspace_root)
        self._tasks_dir = self._workspace_root / "team" / "tasks"
        self._reports_dir = self._workspace_root / "team" / "reports"
        self._audit_dir = self._workspace_root / "team" / "audit"
        self._summary_dir = self._workspace_root / "team" / "summary"

    def _ensure_dirs(self):
        for d in [self._tasks_dir, self._reports_dir, self._audit_dir, self._summary_dir]:
            d.mkdir(parents=True, exist_ok=True)

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action")
        if action == "create":
            return self._create(kwargs)
        elif action == "list":
            return self._list(kwargs)
        elif action == "update":
            return self._update(kwargs)
        elif action == "get":
            return self._get(kwargs)
        else:
            return f"未知操作: {action}"

    def _create(self, params: dict) -> str:
        self._ensure_dirs()

        title = params.get("title", "未命名任务")
        task_id = f"task_{_short_id()}"

        task = {
            "id": task_id,
            "title": title,
            "status": "producing",
            "assigned_role": params.get("assigned_role", "executor"),
            "attempts": 0,
            "max_attempts": params.get("max_attempts", 3),
            "input": {
                "description": params.get("description", ""),
            },
            "output_path": f"team/reports/{task_id}.md",
            "verification": None,
            "created_at": _now_ts(),
            "updated_at": _now_ts(),
        }

        path = self._tasks_dir / f"{task_id}.json"
        atomic_write(path, json.dumps(task, ensure_ascii=False, indent=2))
        logger.info(f"Created task: {task_id} ({title})")
        return json.dumps(task, ensure_ascii=False, indent=2)

    def _list(self, params: dict) -> str:
        self._ensure_dirs()

        filter_status = params.get("filter_status")
        tasks = []

        for path in sorted(self._tasks_dir.glob("task_*.json")):
            try:
                task = json.loads(path.read_text(encoding="utf-8"))
                if not filter_status or task.get("status") == filter_status:
                    tasks.append(task)
            except (json.JSONDecodeError, OSError):
                continue

        if not tasks:
            return "没有找到匹配的任务"

        lines = []
        for t in tasks:
            lines.append(
                f"- [{t['status']}] {t['id']}: {t['title']} "
                f"(attempts={t['attempts']}/{t['max_attempts']})"
            )
        return "\n".join(lines)

    def _update(self, params: dict) -> str:
        task_id = params.get("task_id")
        if not task_id:
            return "Error: update 需要 task_id"
        if not _TASK_ID_RE.fullmatch(task_id):
            return f"Error: 无效的 task_id 格式"

        self._ensure_dirs()
        path = self._tasks_dir / f"{task_id}.json"
        if not path.exists():
            return f"Error: 任务 {task_id} 不存在"

        task = json.loads(path.read_text(encoding="utf-8"))
        new_status = params.get("status")
        if not new_status:
            return "Error: update 需要 status"

        old_status = task["status"]

        # 状态流转校验
        valid_transitions = {
            "producing": ["verifying"],
            "verifying": ["done", "failed"],
            "failed": ["producing"],
            "done": [],
        }

        if new_status not in valid_transitions.get(old_status, []):
            return f"Error: 不允许从 '{old_status}' 转换到 '{new_status}'"

        task["status"] = new_status
        task["updated_at"] = _now_ts()

        if new_status == "verifying":
            task["attempts"] += 1

        # max_attempts 保护：达到上限强制完成
        if new_status == "failed" and task["attempts"] >= task["max_attempts"]:
            task["status"] = "done"
            task["quality_warning"] = True
            logger.warning(f"Task {task_id} reached max_attempts, force-done")

        atomic_write(path, json.dumps(task, ensure_ascii=False, indent=2))
        logger.info(f"Task {task_id}: {old_status} → {task['status']}")
        return json.dumps(task, ensure_ascii=False, indent=2)

    def _get(self, params: dict) -> str:
        task_id = params.get("task_id")
        if not task_id:
            return "Error: get 需要 task_id"
        if not _TASK_ID_RE.fullmatch(task_id):
            return f"Error: 无效的 task_id 格式"

        path = self._tasks_dir / f"{task_id}.json"
        if not path.exists():
            return f"Error: 任务 {task_id} 不存在"

        task = json.loads(path.read_text(encoding="utf-8"))

        # 附带修改意见（如果存在）
        summary_path = self._summary_dir / f"{task_id}.json"
        if summary_path.exists():
            try:
                task["feedback"] = json.loads(summary_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        return json.dumps(task, ensure_ascii=False, indent=2)


class SpawnTool(BaseTool):
    """召唤 SubAgent 执行任务（executor 或 verifier）"""

    name = "spawn"
    description = "召唤 SubAgent 执行子任务。role=executor 执行任务，role=verifier 验证质量。"
    auto_discover = False

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": ["executor", "verifier"],
                    "description": "SubAgent 角色",
                },
                "task_id": {
                    "type": "string",
                    "description": "关联的任务 ID",
                },
                "prompt": {
                    "type": "string",
                    "description": "给 SubAgent 的指令（自包含）",
                },
                "wait": {
                    "type": "boolean",
                    "description": "是否等待结果（默认 true）",
                },
            },
            "required": ["role", "prompt"],
        }

    def __init__(
        self,
        llm_client,
        capability_registry,
        skill_manager,
        long_term_memory,
        roles: dict,
        bia_path: str,
        workspace_root: str,
        sandbox: bool = True,
        max_iterations: int = 50,
    ):
        self._llm_client = llm_client
        self._capability_registry = capability_registry
        self._skill_manager = skill_manager
        self._long_term_memory = long_term_memory
        self._roles = roles
        self._bia_path = bia_path
        self._workspace_root = workspace_root
        self._sandbox = sandbox
        self._max_iterations = max_iterations

    async def execute(self, **kwargs) -> str:
        role_name = kwargs.get("role", "executor")
        prompt = kwargs.get("prompt", "")
        task_id = kwargs.get("task_id")

        if role_name not in self._roles:
            return f"Error: 未知角色 '{role_name}'，可用: {list(self._roles.keys())}"

        role = self._roles[role_name]
        prompt_path = role.get("prompt_path")

        if not prompt_path or not Path(prompt_path).exists():
            return f"Error: 角色 '{role_name}' 的 prompt 模板不存在"

        # 构建 system prompt
        from core.prompt_utils import (
            PromptBuilder, build_tools_section, build_skills_section,
            build_memory_section, build_bia_section,
        )

        builder = PromptBuilder(prompt_path)
        builder.set("workspace_section", (
            f"# Workspace\n\n"
            f"工作区根目录：`{self._workspace_root}`（沙盒模式）\n"
            f"路径直接写相对路径，不要加前缀。"
        ))
        builder.set("bia_section", build_bia_section(self._bia_path))
        builder.set("memory_section", build_memory_section(self._long_term_memory))
        builder.set("tools_section", build_tools_section(self._capability_registry))
        builder.set("skills_section", build_skills_section(self._skill_manager))
        builder.set("task_prompt", prompt)
        builder.set("current_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        system_prompt = builder.build()

        # 工具白名单
        exclude_tools = self._compute_excluded_tools(role)

        # 创建轻量 CapricornGraph（独立 session，避免覆盖主 Agent）
        from agent.agent import CapricornGraph
        from memory.session import SessionManager
        from memory.history import HistoryLog
        from config.settings import WorkspaceConfig

        workspace = WorkspaceConfig(root=self._workspace_root, sandbox=self._sandbox)
        session_manager = SessionManager(workspace)
        history_log = HistoryLog(workspace)

        # 使用独立 thread_id，避免覆盖主 Agent 的 default session
        spawn_thread_id = f"spawn_{_short_id()}"

        graph = CapricornGraph(
            capability_registry=self._capability_registry,
            skill_manager=self._skill_manager,
            session_manager=session_manager,
            long_term_memory=self._long_term_memory,
            history_log=history_log,
            llm_client=self._llm_client,
            sandbox=self._sandbox,
            max_iterations=self._max_iterations,
            exclude_tools=exclude_tools,
            system_prompt_override=system_prompt,
        )

        logger.info(f"Spawning {role_name} for task {task_id or 'adhoc'}")
        result = await graph.run(prompt, thread_id=spawn_thread_id)
        return result

    def _compute_excluded_tools(self, role: dict) -> list:
        """根据角色的工具白名单计算排除列表"""
        role_tools = role.get("tools")
        if role_tools == "all" or not role_tools:
            return ["cron", "spawn"]

        all_tools = [t.name for t in self._capability_registry.get_langchain_tools()]
        excluded = [t for t in all_tools if t not in role_tools]

        for must_exclude in ("cron", "spawn"):
            if must_exclude not in excluded:
                excluded.append(must_exclude)

        return excluded
