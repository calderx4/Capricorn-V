"""
NotificationBus - 事件通知总线

职责：
- 接收 cron 任务执行结果并持久化（JSONL 追加写入）
- SSE 实时推送到订阅者
- 未读通知注入 agent.chat()
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from loguru import logger

from core.utils import atomic_write


class NotificationBus:
    """事件通知总线"""

    def __init__(self):
        self._subscribers: List[asyncio.Queue] = []
        self._path = Path(__file__).resolve().parent.parent / "gateway" / "notifications.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file_lock = asyncio.Lock()

    async def publish(self, event_type: str, data: dict):
        """发布通知（持久化 + 推送到所有订阅者）"""
        notification = {
            "id": uuid.uuid4().hex[:8],
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
            "read": False,
        }
        # 持久化（不阻塞事件循环，受锁保护防 _rewrite 并发丢数据）
        async with self._file_lock:
            await asyncio.to_thread(self._append_notification, notification)

        # 推送到订阅者
        for q in self._subscribers:
            try:
                q.put_nowait(notification)
            except asyncio.QueueFull:
                logger.warning("Subscriber queue full, dropping event")

        logger.info(f"Notification: [{event_type}] {notification['id']}")

    def _append_notification(self, notification: dict):
        """追加写入单条通知（同步，供 to_thread 调用）"""
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(notification, ensure_ascii=False) + "\n")

    def subscribe(self, maxsize: int = 100) -> asyncio.Queue:
        """订阅实时事件（用于 SSE）"""
        q = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._subscribers:
            self._subscribers.remove(q)

    def get_unread(self) -> List[dict]:
        """获取未读通知"""
        return [n for n in self._load_all() if not n.get("read")]

    async def mark_read(self, notification_ids: List[str]):
        """标记为已读"""
        if not notification_ids:
            return
        async with self._file_lock:
            notifications = self._load_all()
            id_set = set(notification_ids)
            changed = False
            for n in notifications:
                if n["id"] in id_set and not n.get("read"):
                    n["read"] = True
                    changed = True
            if changed:
                await asyncio.to_thread(self._rewrite, notifications)

    def get_recent(self, limit: int = 20, unread_only: bool = False) -> List[dict]:
        """获取最近通知"""
        all_n = self._load_all()
        if unread_only:
            all_n = [n for n in all_n if not n.get("read")]
        return all_n[-limit:]

    def cleanup(self, max_age_days: int = 7):
        """清理旧的已读通知"""
        notifications = self._load_all()
        cutoff_dt = datetime.now() - timedelta(days=max_age_days)
        kept = []
        for n in notifications:
            if not n.get("read"):
                kept.append(n)
            else:
                try:
                    if datetime.fromisoformat(n["timestamp"]) > cutoff_dt:
                        kept.append(n)
                except (ValueError, TypeError):
                    kept.append(n)
        if len(kept) < len(notifications):
            self._rewrite(kept)
            logger.info(f"Cleaned up {len(notifications) - len(kept)} old notifications")

    def _load_all(self) -> List[dict]:
        if not self._path.exists():
            return []
        try:
            lines = self._path.read_text(encoding="utf-8").strip().split("\n")
            return [json.loads(line) for line in lines if line.strip()]
        except (json.JSONDecodeError, OSError):
            return []

    def _rewrite(self, notifications: List[dict]):
        """原子重写通知文件"""
        content = "\n".join(json.dumps(n, ensure_ascii=False) for n in notifications) + "\n"
        atomic_write(self._path, content)
