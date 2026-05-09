"""
Trace - 结构化执行链路记录

输出到 logs/trace.jsonl，每行一个 JSON 事件。
与 logs/trace.log（loguru 输出）并存，不冲突。
"""

import json
from datetime import datetime
from pathlib import Path
from threading import Lock

_trace_file: Path = Path("logs/trace.jsonl")
_lock = Lock()


def _ensure_dir():
    _trace_file.parent.mkdir(parents=True, exist_ok=True)


def write_event(event: dict):
    """写入一个 trace 事件"""
    event["ts"] = datetime.now().isoformat(timespec="seconds")
    _ensure_dir()
    with _lock:
        with open(_trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def tool_call(round: int, tool: str, args: dict, latency_ms: int, status: str):
    """记录单个工具调用"""
    # 入参摘要：只保留前 200 字符
    args_summary = {k: (str(v)[:200] if len(str(v)) > 200 else v) for k, v in args.items()}
    write_event({
        "type": "tool_call",
        "round": round,
        "tool": tool,
        "args": args_summary,
        "latency_ms": latency_ms,
        "status": status,
    })


def round_start(round: int, msg_count: int):
    write_event({"type": "round_start", "round": round, "msg_count": msg_count})


def round_end(round: int, tool_calls: int, latency_ms: int, tokens: dict = None):
    event = {
        "type": "round_end",
        "round": round,
        "tool_calls": tool_calls,
        "latency_ms": latency_ms,
    }
    if tokens:
        event["tokens"] = tokens
    write_event(event)


def consolidation(triggered_by: str, messages_before: int, messages_after: int, success: bool):
    write_event({
        "type": "consolidation",
        "triggered_by": triggered_by,
        "messages_before": messages_before,
        "messages_after": messages_after,
        "success": success,
    })
