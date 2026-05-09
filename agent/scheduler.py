"""
CronScheduler - 定时任务调度器

职责：
- 60 秒 tick 轮询 jobs.json
- 串行执行到期任务（队列状态管理）
- 文件锁防止 tick 重叠
- 协程执行：复用主 Agent 组件，排除 cron 工具（防递归）
"""

import asyncio
import fcntl
import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from croniter import croniter
from loguru import logger

from config.settings import Config, WorkspaceConfig
from core.prompt_utils import (
    build_tools_section, build_skills_section, build_memory_section,
    build_bia_section, PromptBuilder,
)
from core.utils import atomic_write


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


def _now_iso() -> str:
    return datetime.now().isoformat()


def parse_interval(schedule: str) -> timedelta:
    """解析 'every 30m' / 'every 2h' / 'every 1d' 格式"""
    m = re.match(r"every\s+(\d+)([mhd])", schedule)
    if not m:
        raise ValueError(f"Invalid interval format: {schedule}")
    val, unit = int(m.group(1)), m.group(2)
    if unit == "m":
        return timedelta(minutes=val)
    if unit == "h":
        return timedelta(hours=val)
    return timedelta(days=val)


def parse_delay(schedule: str) -> timedelta:
    """解析 '2h' / '30m' / '1d' 格式（一次性延迟）"""
    m = re.match(r"^(\d+)([mhd])$", schedule)
    if not m:
        raise ValueError(f"Invalid delay format: {schedule}")
    val, unit = int(m.group(1)), m.group(2)
    if unit == "m":
        return timedelta(minutes=val)
    if unit == "h":
        return timedelta(hours=val)
    return timedelta(days=val)


def calc_next_run(schedule: str) -> str:
    """计算下次执行时间"""
    now = datetime.now()

    # cron 表达式：含空格且不以 every 开头
    if " " in schedule and not schedule.startswith("every"):
        return croniter(schedule, now).get_next(datetime).isoformat()

    # 间隔：'every 30m'
    if schedule.startswith("every"):
        return (now + parse_interval(schedule)).isoformat()

    # 纯延迟：'2h' / '30m'
    if re.match(r"^\d+[mhd]$", schedule):
        return (now + parse_delay(schedule)).isoformat()

    # 时间字符串：'13:25' → 转为 cron 表达式
    if re.match(r"^\d{1,2}:\d{2}$", schedule):
        h, m = schedule.split(":")
        cron_expr = f"{m} {h} * * *"
        return croniter(cron_expr, now).get_next(datetime).isoformat()

    # ISO datetime：'2026-04-29T13:25:00'
    try:
        target = datetime.fromisoformat(schedule)
        if target <= now:
            raise ValueError(f"时间 {schedule} 已过")
        return target.isoformat()
    except ValueError:
        raise ValueError(
            f"不支持的调度格式: '{schedule}'。"
            "支持: cron表达式('0 9 * * *'), 间隔('every 30m'), "
            "延迟('2h'/'30m'), 时间('13:25'), 日期时间('2026-04-29T15:00:00')"
        )


def _infer_type(schedule: str) -> str:
    """从 schedule 格式推断任务类型"""
    if re.match(r"^\d+[mhd]$", schedule):
        return "once"
    if re.match(r"^\d{1,2}:\d{2}$", schedule):
        return "recurring"  # "13:25" → calc_next_run 生成每日 cron
    try:
        datetime.fromisoformat(schedule)
        return "once"
    except ValueError:
        pass
    return "recurring"


class CronScheduler:
    """定时任务调度器"""

    TICK_INTERVAL = 60  # 默认 60 秒

    def __init__(self, config: Config):
        self.config = config
        self.cron_cfg = config.cron
        self.TICK_INTERVAL = self.cron_cfg.tick_interval

        self.jobs_path = Path("gateway/jobs.json")
        self.lock_path = Path("gateway/.tick.lock")
        self.output_dir = Path("gateway/output")
        self.workspaces_dir = Path("gateway/workspaces")

        self._lock_fd = None
        self._initialized = False
        self._lock = asyncio.Lock()
        self._running = False

        # 复用主 Agent 的组件（由 initialize 注入）
        self._llm_client = None
        self._capability_registry = None
        self._skill_manager = None
        self._long_term_memory = None
        self._cron_prompt_path = None  # 垂类提供的 cron prompt 路径
        self._bia_path = None

    def initialize(self, llm_client, capability_registry, skill_manager, long_term_memory, notification_bus=None, cron_prompt_path=None, bia_path=None):
        """注入主 Agent 的共享组件"""
        self._llm_client = llm_client
        self._capability_registry = capability_registry
        self._skill_manager = skill_manager
        self._long_term_memory = long_term_memory
        self._notification_bus = notification_bus
        self._cron_prompt_path = cron_prompt_path
        self._bia_path = bia_path
        self._initialized = True
        logger.info("CronScheduler initialized with shared agent components")

    # ── 任务管理（async，受 asyncio.Lock 保护）──────────

    async def create_job(self, **kwargs) -> dict:
        """创建任务，返回 job dict"""
        async with self._lock:
            schedule = kwargs.get("schedule", "every 1h")
            name = kwargs.get("name", "unnamed")
            job_id = _short_id()

            job_type = kwargs.get("type") or _infer_type(schedule)
            workdir_name = re.sub(r"[^\w-]", "_", name)
            job = {
                "id": job_id,
                "name": name,
                "type": job_type,
                "schedule": schedule,
                "prompt": kwargs.get("prompt", ""),
                "fresh_session": kwargs.get("fresh_session", self.config.cron.fresh_session),
                "system_prompt": kwargs.get("system_prompt"),
                "workdir": str(self.workspaces_dir / workdir_name),
                "next_run_at": calc_next_run(schedule),
                "status": "active",
                "created_at": _now_iso(),
                "last_run_at": None,
                "last_run_status": None,
                "repeat": kwargs.get("repeat"),
                "end_at": kwargs.get("end_at"),
                "tags": kwargs.get("tags", []),
            }

            jobs = self._load_jobs()
            jobs.append(job)
            self._save_jobs(jobs)

            Path(job["workdir"]).mkdir(parents=True, exist_ok=True)
            logger.info(f"Created cron job: {job_id} ({name}, type={job_type})")
            return job

    def list_jobs(self) -> List[dict]:
        return self._load_jobs()

    def get_job(self, job_id: str) -> Optional[dict]:
        for job in self._load_jobs():
            if job["id"] == job_id:
                return job
        return None

    async def update_job(self, job_id: str, **kwargs) -> Optional[dict]:
        async with self._lock:
            jobs = self._load_jobs()
            for job in jobs:
                if job["id"] == job_id:
                    for k, v in kwargs.items():
                        if k in ("type", "end_at") or (v is not None and k in job):
                            job[k] = v
                    if "schedule" in kwargs:
                        job["next_run_at"] = calc_next_run(job["schedule"])
                    self._save_jobs(jobs)
                    logger.info(f"Updated cron job: {job_id}")
                    return job
            return None

    async def pause_job(self, job_id: str) -> Optional[dict]:
        async with self._lock:
            jobs = self._load_jobs()
            for job in jobs:
                if job["id"] == job_id:
                    job["status"] = "paused"
                    self._save_jobs(jobs)
                    return job
            return None

    async def resume_job(self, job_id: str) -> Optional[dict]:
        async with self._lock:
            jobs = self._load_jobs()
            for job in jobs:
                if job["id"] == job_id:
                    job["status"] = "active"
                    job["next_run_at"] = calc_next_run(job["schedule"])
                    self._save_jobs(jobs)
                    return job
            return None

    async def remove_job(self, job_id: str) -> bool:
        async with self._lock:
            jobs = self._load_jobs()
            before = len(jobs)
            jobs = [j for j in jobs if j["id"] != job_id]
            if len(jobs) < before:
                self._save_jobs(jobs)
                logger.info(f"Removed cron job: {job_id}")
                return True
            return False

    async def run_job_now(self, job_id: str) -> Optional[dict]:
        """立即触发一次任务执行"""
        async with self._lock:
            jobs = self._load_jobs()
            for job in jobs:
                if job["id"] == job_id:
                    job["next_run_at"] = _now_iso()
                    if job["status"] == "paused":
                        job["status"] = "active"
                    self._save_jobs(jobs)
                    logger.info(f"Triggered immediate run for job: {job_id}")
                    return job
            return None

    # ── Tick 循环 ─────────────────────────────────────

    async def run(self):
        """主 tick 循环"""
        if not self._initialized:
            logger.error("CronScheduler not initialized, cannot start tick loop")
            return

        logger.info(f"CronScheduler tick loop started (interval={self.TICK_INTERVAL}s)")

        # 启动时恢复中断的任务
        self._recover_jobs()
        self._running = True

        while self._running:
            try:
                await self.tick()
            except Exception as e:
                logger.error(f"Tick error: {e}")
            await asyncio.sleep(self.TICK_INTERVAL)

        # 循环退出后释放文件锁
        self._release_lock()
        logger.info("CronScheduler tick loop stopped")

    def stop(self):
        """停止 tick 循环"""
        self._running = False

    async def tick(self):
        if not self._acquire_lock():
            return

        try:
            # Phase 1: 标记到期任务（受 asyncio.Lock 保护）
            async with self._lock:
                jobs = self._load_jobs()
                now = datetime.now()

                queued_ids = []
                for job in jobs:
                    if job["status"] == "active":
                        next_run = datetime.fromisoformat(job["next_run_at"])
                        if next_run <= now:
                            job["status"] = "queued"
                            queued_ids.append(job["id"])

                if queued_ids:
                    self._save_jobs(jobs)

            # Phase 2: 逐个执行（释放 asyncio.Lock，允许 API 调用）
            for job_id in queued_ids:
                # 标记 running
                async with self._lock:
                    jobs = self._load_jobs()
                    job = next((j for j in jobs if j["id"] == job_id and j["status"] == "queued"), None)
                    if not job:
                        continue
                    job["status"] = "running"
                    self._save_jobs(jobs)
                    started = _now_iso()

                # 执行（长时间运行，不持有锁）
                try:
                    result = await self._execute_job(job)
                    self._save_result(job, "success", result, started_at=started)
                    last_run_status = "success"
                except Exception as e:
                    logger.error(f"Job {job['id']} failed: {e}")
                    self._save_result(job, "failed", str(e), started_at=started)
                    last_run_status = "failed"
                    result = f"执行失败: {e}"

                # 发布通知
                if self._notification_bus:
                    await self._notification_bus.publish("cron_result", {
                        "job_id": job["id"],
                        "job_name": job["name"],
                        "status": last_run_status,
                        "message": (result or "")[:500],
                    })

                # 更新下次执行时间
                async with self._lock:
                    jobs = self._load_jobs()
                    self._update_next_run_inline(jobs, job["id"], last_run_status)
                    self._save_jobs(jobs)

        finally:
            self._release_lock()

    def _build_cron_prompt(self, job: dict) -> str:
        """构建 cron 专用 system prompt（自包含，不嵌套 system.md）"""
        builder = PromptBuilder(self._cron_prompt_path)

        workspace_section = (
            f"# Workspace\n\n"
            f"工作区根目录：`{job['workdir']}`（沙盒模式）\n"
            f"路径直接写相对路径，不要加前缀。"
        )
        builder.set("workspace_section", workspace_section)
        builder.set("bia_section", build_bia_section(self._bia_path))

        fresh = job.get("fresh_session", False)
        builder.set("memory_section", "" if fresh else build_memory_section(self._long_term_memory))
        builder.set("tools_section", build_tools_section(self._capability_registry))
        builder.set("skills_section", build_skills_section(self._skill_manager))
        builder.set("task_prompt", job.get("prompt", ""))
        builder.set("current_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        return builder.build()

    async def _execute_job(self, job: dict) -> str:
        """执行单个任务：创建轻量 CapricornGraph"""
        from agent.agent import CapricornGraph
        from memory.session import SessionManager
        from memory.history import HistoryLog

        workdir = Path(job["workdir"])
        workdir.mkdir(parents=True, exist_ok=True)

        workspace = WorkspaceConfig(root=str(workdir), sandbox=True)
        session_manager = SessionManager(workspace)
        history_log = HistoryLog(workspace)

        fresh = job.get("fresh_session", False)
        memory = None if fresh else self._long_term_memory
        cron_prompt = self._build_cron_prompt(job)

        graph = CapricornGraph(
            capability_registry=self._capability_registry,
            skill_manager=self._skill_manager,
            session_manager=session_manager,
            long_term_memory=memory,
            history_log=history_log,
            llm_client=self._llm_client,
            sandbox=True,
            max_iterations=self.config.agent.get("max_iterations", 50),
            exclude_tools=["cron"],
            system_prompt_override=cron_prompt,
        )

        logger.info(f"Executing cron job: {job['id']} ({job['name']})")
        result = await graph.run("执行上述任务。", thread_id="default")
        return result

    # ── 状态管理 ──────────────────────────────────────

    def _update_next_run_inline(self, jobs: List[dict], job_id: str, last_run_status: str):
        """在已加载的 jobs 列表上原地更新（避免重新加载）"""
        now = datetime.now()
        for j in jobs:
            if j["id"] == job_id:
                j["last_run_at"] = _now_iso()
                j["last_run_status"] = last_run_status

                # once → 执行完直接完成
                if j.get("type") == "once":
                    j["status"] = "completed"
                    return

                # end_at 到期 → 完成
                if j.get("end_at"):
                    if now >= datetime.fromisoformat(j["end_at"]):
                        j["status"] = "completed"
                        return

                # repeat 倒计时 → 完成
                if j.get("repeat") is not None:
                    j["repeat"] -= 1
                    if j["repeat"] <= 0:
                        j["status"] = "completed"
                        return

                # 继续
                j["status"] = "active"
                j["next_run_at"] = calc_next_run(j["schedule"])
                return

    def _recover_jobs(self):
        """启动时将 queued/running 状态重置为 active"""
        jobs = self._load_jobs()
        changed = False
        for job in jobs:
            if job["status"] in ("queued", "running"):
                job["status"] = "active"
                job["next_run_at"] = calc_next_run(job["schedule"])
                changed = True
        if changed:
            self._save_jobs(jobs)
            logger.info("Recovered interrupted cron jobs")

    # ── 持久化 ────────────────────────────────────────

    def _load_jobs(self) -> List[dict]:
        if not self.jobs_path.exists():
            return []
        try:
            content = self.jobs_path.read_text(encoding="utf-8")
            jobs = json.loads(content)
            # 旧 job 兼容：无 type 字段时自动补上
            for job in jobs:
                if "type" not in job:
                    job["type"] = _infer_type(job.get("schedule", ""))
            return jobs
        except json.JSONDecodeError as e:
            logger.critical(f"jobs.json 损坏: {e}，已备份并重置")
            backup = self.jobs_path.with_suffix(".json.bak")
            self.jobs_path.rename(backup)
            return []
        except OSError as e:
            logger.error(f"Failed to load jobs.json: {e}")
            return []

    def _save_jobs(self, jobs: List[dict]):
        atomic_write(
            self.jobs_path,
            json.dumps(jobs, ensure_ascii=False, indent=2),
        )

    def _save_result(self, job: dict, status: str, response: str, started_at: str = None):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        job_dir = self.output_dir / job["id"]
        job_dir.mkdir(parents=True, exist_ok=True)

        result = {
            "run_id": _short_id(),
            "job_id": job["id"],
            "started_at": started_at or _now_iso(),
            "finished_at": _now_iso(),
            "status": status,
            "response": response[:2000] if response else None,
            "error": None if status == "success" else response,
        }
        path = job_dir / f"{result['run_id']}.json"
        atomic_write(path, json.dumps(result, ensure_ascii=False, indent=2))

    # ── 文件锁 ────────────────────────────────────────

    def _acquire_lock(self) -> bool:
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._lock_fd = open(self.lock_path, "w")
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, OSError):
            if self._lock_fd:
                self._lock_fd.close()
                self._lock_fd = None
            return False

    def _release_lock(self):
        if self._lock_fd:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            self._lock_fd.close()
            self._lock_fd = None
