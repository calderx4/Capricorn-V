"""
Gateway - HTTP 服务

职责：
- POST /chat：远程调用 agent（共享 session）
- POST /task：异步任务
- GET /task/{task_id}：查询任务状态
- GET /jobs：列出 cron 任务
- GET /health：健康检查
- GET /events：SSE 实时推送通知
- GET /notifications：查询通知列表
- POST /notifications/read：标记通知已读
"""

import asyncio
import hmac
import json
import os
import re
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict

from aiohttp import web
from loguru import logger

from core.utils import atomic_write

MAX_PROMPT_LENGTH = 50000
MAX_CONCURRENT_TASKS = 20
MAX_SSE_CLIENTS = 50
TASK_ID_RE = re.compile(r'^[0-9a-f]{8}$')


@web.middleware
async def security_headers_middleware(request, handler):
    """安全响应头"""
    resp = await handler(request)
    if isinstance(resp, web.StreamResponse):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp


class Gateway:
    """HTTP Gateway 服务"""

    def __init__(self, agent, config, notification_bus=None, webui: bool = False):
        self.agent = agent
        self.config = config
        self._notification_bus = notification_bus
        self.webui = webui
        self.host = config.gateway.host
        self.port = config.gateway.port
        self.start_time = time.time()
        self.tasks_dir = Path(__file__).resolve().parent.parent / "gateway" / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._thread_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._api_key = os.environ.get("GATEWAY_API_KEY", "")

    async def start(self):
        """启动 HTTP 服务"""
        middlewares = [security_headers_middleware]
        if self._api_key:
            middlewares.append(self._make_auth_middleware())

        app = web.Application(middlewares=middlewares)
        app.add_routes([
            web.post("/chat", self._handle_chat),
            web.post("/task", self._handle_task_create),
            web.get("/task/{task_id}", self._handle_task_status),
            web.get("/jobs", self._handle_jobs),
            web.get("/health", self._handle_health),
            web.get("/events", self._handle_sse),
            web.get("/notifications", self._handle_notifications),
            web.post("/notifications/read", self._handle_notifications_read),
        ])

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info(f"Gateway started on {self.host}:{self.port}" + (" (with WebUI)" if self.webui else ""))
        if self._api_key:
            logger.info("Gateway authentication enabled")

        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await runner.cleanup()

    @property
    def _cron_scheduler(self):
        return getattr(self.agent, "_cron_scheduler", None)

    @staticmethod
    def _validate_prompt(body: dict):
        """校验 prompt，返回 (prompt, error_response)"""
        prompt = body.get("prompt", "").strip()
        if not prompt:
            return None, web.json_response({"error": "prompt is required"}, status=400)
        if len(prompt) > MAX_PROMPT_LENGTH:
            return None, web.json_response({"error": f"prompt too long (max {MAX_PROMPT_LENGTH})"}, status=400)
        return prompt, None

    def _make_auth_middleware(self):
        """创建 API Key 认证中间件（设置 GATEWAY_API_KEY 环境变量启用）"""
        api_key = self._api_key

        @web.middleware
        async def auth_middleware(request, handler):
            if request.path == "/health":
                return await handler(request)
            auth = request.headers.get("Authorization", "")
            token = auth.removeprefix("Bearer ").strip()
            if not hmac.compare_digest(token, api_key):
                return web.json_response({"error": "Unauthorized"}, status=401)
            return await handler(request)

        return auth_middleware

    # ── Handlers ──────────────────────────────────────

    async def _handle_chat(self, request: web.Request) -> web.Response:
        """POST /chat"""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        prompt, err = self._validate_prompt(body)
        if err:
            return err

        thread_id = body.get("thread_id", "default")

        try:
            lock = self._get_thread_lock(thread_id)
            async with lock:
                response = await self.agent.chat(prompt, thread_id=thread_id)
            return web.json_response({"response": response})
        except Exception as e:
            logger.error(f"/chat error: {e}")
            return web.json_response({"error": "Internal server error"}, status=500)

    async def _handle_task_create(self, request: web.Request) -> web.Response:
        """POST /task"""
        if len(self._running_tasks) >= MAX_CONCURRENT_TASKS:
            return web.json_response({"error": "Too many concurrent tasks"}, status=429)

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        prompt, err = self._validate_prompt(body)
        if err:
            return err

        task_id = uuid.uuid4().hex[:8]
        task_data = {
            "task_id": task_id,
            "status": "pending",
            "prompt": prompt,
            "result": None,
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "finished_at": None,
            "error": None,
        }
        self._save_task(task_data)

        asyncio_task = asyncio.create_task(self._run_task(task_id, prompt))
        self._running_tasks[task_id] = asyncio_task

        return web.json_response({"task_id": task_id, "status": "pending"})

    async def _handle_task_status(self, request: web.Request) -> web.Response:
        """GET /task/{task_id}"""
        task_id = request.match_info["task_id"]
        if not TASK_ID_RE.fullmatch(task_id):
            return web.json_response({"error": "Invalid task_id"}, status=400)
        task_data = self._load_task(task_id)
        if not task_data:
            return web.json_response({"error": "Task not found"}, status=404)
        return web.json_response(task_data)

    async def _handle_jobs(self, request: web.Request) -> web.Response:
        """GET /jobs — 列出 cron 任务"""
        scheduler = self._cron_scheduler
        if not scheduler:
            return web.json_response({"jobs": []})
        return web.json_response({"jobs": scheduler.list_jobs()})

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /health"""
        scheduler = self._cron_scheduler
        cron_jobs = len(scheduler.list_jobs()) if scheduler else 0

        return web.json_response({
            "status": "ok",
            "cron_jobs": cron_jobs,
            "uptime": int(time.time() - self.start_time),
        })

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        """GET /events — SSE 实时推送通知"""
        if not self._notification_bus:
            return web.json_response({"error": "Notification service not available"}, status=503)

        if len(self._notification_bus._subscribers) >= MAX_SSE_CLIENTS:
            return web.json_response({"error": "Too many SSE connections"}, status=429)

        resp = web.StreamResponse()
        resp.content_type = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Connection"] = "keep-alive"
        await resp.prepare(request)

        queue = self._notification_bus.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    data = json.dumps(event, ensure_ascii=False)
                    resp.write(f"data: {data}\n\n".encode("utf-8"))
                    await resp.drain()
                except asyncio.TimeoutError:
                    resp.write(b":keepalive\n\n")
                    await resp.drain()
        except (ConnectionResetError, ConnectionError, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.debug(f"SSE stream error: {e}")
        finally:
            self._notification_bus.unsubscribe(queue)

        return resp

    async def _handle_notifications(self, request: web.Request) -> web.Response:
        """GET /notifications — 查询通知列表"""
        if not self._notification_bus:
            return web.json_response({"notifications": []})

        unread_only = request.query.get("unread", "false").lower() == "true"
        try:
            limit = int(request.query.get("limit", "20"))
            limit = max(1, min(limit, 100))
        except ValueError:
            limit = 20
        notifications = self._notification_bus.get_recent(limit=limit, unread_only=unread_only)
        return web.json_response({"notifications": notifications})

    async def _handle_notifications_read(self, request: web.Request) -> web.Response:
        """POST /notifications/read — 标记通知已读"""
        if not self._notification_bus:
            return web.json_response({"error": "Notification service not available"}, status=503)

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        ids = body.get("ids", [])
        if not isinstance(ids, list) or len(ids) > 100:
            return web.json_response({"error": "Invalid ids parameter"}, status=400)
        if not all(isinstance(i, str) for i in ids):
            return web.json_response({"error": "Invalid id format"}, status=400)
        await self._notification_bus.mark_read(ids)
        return web.json_response({"ok": True})

    # ── Thread Lock LRU ───────────────────────────────

    def _get_thread_lock(self, thread_id: str) -> asyncio.Lock:
        if thread_id in self._thread_locks:
            self._thread_locks.move_to_end(thread_id)
            return self._thread_locks[thread_id]
        lock = asyncio.Lock()
        self._thread_locks[thread_id] = lock
        if len(self._thread_locks) > 1024:
            self._thread_locks.popitem(last=False)
        return lock

    # ── 异步任务执行 ──────────────────────────────────

    async def _run_task(self, task_id: str, prompt: str):
        task_data = self._load_task(task_id)
        if not task_data:
            logger.error(f"Task {task_id} data file missing")
            self._running_tasks.pop(task_id, None)
            return
        task_data["status"] = "running"
        self._save_task(task_data)

        try:
            result = await self.agent.chat(prompt, thread_id=f"task_{task_id}")
            task_data["status"] = "done"
            task_data["result"] = result
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            task_data["status"] = "failed"
            task_data["error"] = "Internal error"
        finally:
            task_data["finished_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            self._save_task(task_data)
            self._running_tasks.pop(task_id, None)

    # ── 持久化 ────────────────────────────────────────

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def _save_task(self, data: dict):
        path = self._task_path(data["task_id"])
        atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))

    def _load_task(self, task_id: str) -> dict | None:
        path = self._task_path(task_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

