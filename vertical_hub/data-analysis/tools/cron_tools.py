"""
Cron Tool - 定时任务管理工具

LLM 通过 Function Calling 管理 cron 任务。
支持 action 参数式 API：create | list | update | pause | resume | run | remove
"""

import json
from typing import Any, Dict

from loguru import logger

from core.base_tool import BaseTool


class CronTool(BaseTool):
    """定时任务管理工具"""

    auto_discover = False  # 手动注册，需要 scheduler 引用

    def __init__(self, scheduler):
        self._scheduler = scheduler

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return (
            "定时任务管理工具。\n"
            "用法：\n"
            "  create — 创建任务（必填：prompt、schedule）\n"
            "  list — 列出所有定时任务\n"
            "  update — 更新任务配置（必填：job_id）\n"
            "  pause — 暂停任务（必填：job_id）\n"
            "  resume — 恢复任务（必填：job_id）\n"
            "  run — 立即触发任务（必填：job_id）\n"
            "  remove — 删除任务（必填：job_id）\n"
            "role 说明：\n"
            "  executor — 执行任务的角色，拥有全部工具，使用 executor 角色模板\n"
            "  verifier — 验证质量的角色，只拥有检查/纠偏相关工具，使用 verifier 角色模板\n"
            "  传了 role 后，prompt 只需写简短触发语（如'执行任务'、'执行质量验证流程。'），角色模板会自动注入完整指令。\n"
            "  不传 role 时使用通用 cron 模板，prompt 需要自包含全部指令。\n"
            "schedule 格式：\n"
            "  一次性任务（type=once）：\n"
            "    '3m' → 3分钟后执行；'2h' → 2小时后；'1d' → 明天同时间\n"
            "    '14:00' → 今天14:00；'2026-05-03T09:00:00' → 指定日期时间\n"
            "  重复任务（type=recurring，可配合 repeat/end_at 限制次数）：\n"
            "    'every 30m' → 每30分钟；'every 2h' → 每2小时\n"
            "    '9:00' → 每天9:00；'14:30' → 每天14:30\n"
            "    '0 9 * * 1-5' → 工作日每天9点（标准 cron）\n"
            "  repeat=数字 → recurring 时生效，执行指定次数后自动停止（不传则无限循环）\n"
            "  end_at=ISO时间 → recurring 时生效，到期后自动停止\n"
            "  注意：数字必须带单位（m/h/d），直接写'2'无效。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "update", "pause", "resume", "run", "remove"],
                    "description": "操作类型",
                },
                "name": {
                    "type": "string",
                    "description": "任务名称（create/update 时使用）",
                },
                "type": {
                    "type": "string",
                    "enum": ["once", "recurring"],
                    "description": "任务类型。once=执行一次，recurring=按 schedule 重复。不传时自动推断",
                },
                "schedule": {
                    "type": "string",
                    "description": (
                        "调度时间，格式由 type 决定："
                        "once → 延迟('3m'/'2h'/'1d')、时间('13:25')、日期时间('2026-04-30T14:00:00')；"
                        "recurring → 间隔('every 30m'/'every 2h')、每天时间('13:25')、cron表达式('0 9 * * 1-5')。"
                        "纯数字如'2'无效，必须带单位 m/h/d。"
                        "配合 repeat 或 end_at 可限制 recurring 任务的执行次数或截止时间。"
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": "任务执行指令，必须自包含（无对话历史）",
                },
                "job_id": {
                    "type": "string",
                    "description": "目标任务 ID（update/pause/resume/run/remove 时使用）",
                },
                "fresh_session": {
                    "type": "boolean",
                    "description": "是否使用独立会话（自定义记忆和 prompt）。默认 false，沿用主 agent 记忆",
                },
                "system_prompt": {
                    "type": "string",
                    "description": "fresh_session=true 时生效，自定义 agent 人设和行为",
                },
                "repeat": {
                    "type": "integer",
                    "description": "仅 recurring 生效。不传=无限循环，传数字=执行指定次数后停止",
                },
                "end_at": {
                    "type": "string",
                    "description": "仅 recurring 生效。截止时间 ISO 格式，如 '2026-05-03T00:00:00'。到期后自动停止",
                },
                "role": {
                    "type": "string",
                    "description": (
                        "角色名称。传了 role 后使用角色专属模板和工具白名单，prompt 只需简短触发语。"
                        "executor=执行任务（全工具），verifier=验证质量（检查/纠偏工具）。"
                        "不传则使用通用 cron 模板。"
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "任务标签",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, **kwargs) -> str:
        try:
            if action == "create":
                return await self._handle_create(**kwargs)
            elif action == "list":
                return self._handle_list()
            elif action == "update":
                return await self._handle_update(**kwargs)
            elif action == "pause":
                return await self._handle_pause(**kwargs)
            elif action == "resume":
                return await self._handle_resume(**kwargs)
            elif action == "run":
                return await self._handle_run(**kwargs)
            elif action == "remove":
                return await self._handle_remove(**kwargs)
            else:
                return f"Error: Unknown action '{action}'"
        except Exception as e:
            logger.error(f"Cron tool error: {e}")
            return f"Error: {str(e)}"

    async def _handle_create(self, **kwargs) -> str:
        if not kwargs.get("prompt"):
            return "Error: 'prompt' is required for create action"
        if not kwargs.get("schedule"):
            return "Error: 'schedule' is required for create action"

        job = await self._scheduler.create_job(**kwargs)
        return f"定时任务已创建:\n{json.dumps(job, ensure_ascii=False, indent=2)}"

    def _handle_list(self) -> str:
        jobs = self._scheduler.list_jobs()
        if not jobs:
            return "当前没有定时任务"
        return f"共 {len(jobs)} 个定时任务:\n{json.dumps(jobs, ensure_ascii=False, indent=2)}"

    async def _handle_update(self, **kwargs) -> str:
        job_id = kwargs.get("job_id")
        if not job_id:
            return "Error: 'job_id' is required for update action"

        updates = {k: v for k, v in kwargs.items() if k not in ("action", "job_id") and v is not None}
        job = await self._scheduler.update_job(job_id, **updates)
        if not job:
            return f"Error: Job '{job_id}' not found"
        return f"定时任务已更新:\n{json.dumps(job, ensure_ascii=False, indent=2)}"

    async def _handle_pause(self, **kwargs) -> str:
        job_id = kwargs.get("job_id")
        if not job_id:
            return "Error: 'job_id' is required for pause action"
        job = await self._scheduler.pause_job(job_id)
        if not job:
            return f"Error: Job '{job_id}' not found"
        return f"定时任务已暂停: {job['name']} ({job_id})"

    async def _handle_resume(self, **kwargs) -> str:
        job_id = kwargs.get("job_id")
        if not job_id:
            return "Error: 'job_id' is required for resume action"
        job = await self._scheduler.resume_job(job_id)
        if not job:
            return f"Error: Job '{job_id}' not found"
        return f"定时任务已恢复: {job['name']} ({job_id})"

    async def _handle_run(self, **kwargs) -> str:
        job_id = kwargs.get("job_id")
        if not job_id:
            return "Error: 'job_id' is required for run action"
        job = await self._scheduler.run_job_now(job_id)
        if not job:
            return f"Error: Job '{job_id}' not found"
        return f"定时任务已触发立即执行: {job['name']} ({job_id})"

    async def _handle_remove(self, **kwargs) -> str:
        job_id = kwargs.get("job_id")
        if not job_id:
            return "Error: 'job_id' is required for remove action"
        if await self._scheduler.remove_job(job_id):
            return f"定时任务已删除: {job_id}"
        return f"Error: Job '{job_id}' not found"
