"""
Quality Tools — 质量检查与质量信号工具（数据分析垂类）

自进化基础设施的一部分：
- QualityCheckTool: 按预设标准检查报告质量（纯正则，不调 LLM）
- QualitySignalTool: 记录和查询质量信号
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from loguru import logger

from core.base_tool import BaseTool
from core.utils import atomic_write


# ── V1 数据分析检查规则 ──────────────────────────────────────

SECTION_HEADINGS = ["关键发现", "表结构"]

COMPARISON_WORDS = [
    "vs", "相比", "对比", "比起", "高于", "低于", "超过", "不及",
    "增长", "下降", "环比", "同比", "翻倍", "减半", "相差", "差距",
]

ANOMALY_WORDS = [
    "异常", "偏离", "突变", "意外", "反常", "不寻常",
    "注意", "警示", "风险", "缺失", "断层", "缺口", "稀少",
]

NUMBER_PATTERN = re.compile(r"\d+\.?\d*%?")
HEADING_PATTERN = re.compile(r"^#{1,6}\s+", re.MULTILINE)
MIN_LENGTH = 100


def _check_report(content: str) -> Dict[str, Any]:
    """对分析报告文本执行 V1 自动检查。"""
    details: Dict[str, Any] = {
        "has_numbers": len(NUMBER_PATTERN.findall(content)) >= 3,
        "has_headings": bool(HEADING_PATTERN.search(content)),
        "min_length": len(content.strip()) >= MIN_LENGTH,
        "section_complete": all(h in content for h in SECTION_HEADINGS),
        "has_comparison": any(w in content for w in COMPARISON_WORDS),
        "has_anomaly": any(w in content for w in ANOMALY_WORDS),
    }
    fail_items = [k for k, v in details.items() if not v]
    return {
        "pass": len(fail_items) == 0,
        "details": details,
        "fail_count": len(fail_items),
        "fail_items": fail_items,
    }


# ── QualityCheckTool ─────────────────────────────────────────


class QualityCheckTool(BaseTool):
    """按预设标准检查分析报告质量"""

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True):
        self._workspace_root = workspace_root
        self._sandbox = sandbox

    @classmethod
    def from_config(cls, config: dict) -> "QualityCheckTool":
        return cls(config["workspace_root"], config.get("sandbox", True))

    @property
    def name(self) -> str:
        return "quality_check"

    @property
    def description(self) -> str:
        return (
            "检查分析报告质量（V1 自动检查）。适用场景：执行 Cron 产出报告后自检，"
            "或监督 Cron 扫描历史报告。\n"
            "检查项：结构完整（含'关键发现'和'表结构'）、有具体数字（≥3）、"
            "有对比分析（≥1词）、有异常发现（≥1词）。\n"
            "输入报告文本，返回 pass/fail 及各维度详情。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "report": {
                    "type": "string",
                    "description": "要检查的报告文本（Markdown）",
                },
            },
            "required": ["report"],
        }

    async def execute(self, report: str) -> str:
        try:
            result = _check_report(report)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"quality_check failed: {e}")
            return json.dumps({"pass": False, "error": str(e)}, ensure_ascii=False)


# ── QualitySignalTool ────────────────────────────────────────


class QualitySignalTool(BaseTool):
    """记录和查询质量信号"""

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True):
        self._workspace_root = workspace_root
        self._sandbox = sandbox

    @classmethod
    def from_config(cls, config: dict) -> "QualitySignalTool":
        return cls(config["workspace_root"], config.get("sandbox", True))

    @property
    def name(self) -> str:
        return "quality_signal"

    @property
    def description(self) -> str:
        return (
            "记录或查询质量信号。action=record 时记录一条质量信号（任务完成时调用），"
            "action=list 时查询最近的信号，action=summary 时统计通过率。\n"
            "质量信号存储在工作区 team/quality_signals/ 目录。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["record", "list", "summary"],
                    "description": "record=记录信号，list=查询列表，summary=统计汇总",
                },
                "task_id": {
                    "type": "string",
                    "description": "任务 ID（record 时必填）",
                },
                "quality": {
                    "type": "object",
                    "description": "quality_check 的返回结果（record 时必填）",
                },
                "limit": {
                    "type": "integer",
                    "description": "查询数量限制（list/summary 时使用，默认 20）",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        task_id: str = None,
        quality: dict = None,
        limit: int = 20,
    ) -> str:
        try:
            signals_dir = Path(self._workspace_root) / "team" / "quality_signals"
            signals_dir.mkdir(parents=True, exist_ok=True)

            if action == "record":
                if not task_id or not quality:
                    return "Error: task_id and quality are required for record"
                signal = {
                    "task_id": task_id,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "status": "completed",
                    "quality": quality,
                }
                safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', task_id)
                signal_path = signals_dir / f"{safe_name}.json"
                atomic_write(signal_path, json.dumps(signal, ensure_ascii=False, indent=2))
                logger.info(f"Quality signal recorded: {task_id}")
                return f"Quality signal recorded for {task_id}"

            elif action == "list":
                files = sorted(signals_dir.glob("*.json"), reverse=True)
                signals = []
                for f in files[:limit]:
                    try:
                        signals.append(json.loads(f.read_text(encoding="utf-8")))
                    except (json.JSONDecodeError, Exception):
                        continue
                return json.dumps(signals, ensure_ascii=False, indent=2)

            elif action == "summary":
                files = sorted(signals_dir.glob("*.json"), reverse=True)
                signals = []
                for f in files[:limit]:
                    try:
                        signals.append(json.loads(f.read_text(encoding="utf-8")))
                    except (json.JSONDecodeError, Exception):
                        continue

                if not signals:
                    return json.dumps({"total": 0, "pass_rate": 0}, ensure_ascii=False)

                total = len(signals)
                passed = sum(1 for s in signals if s.get("quality", {}).get("pass", False))
                fail_counts: Dict[str, int] = {}
                for s in signals:
                    for item in s.get("quality", {}).get("fail_items", []):
                        fail_counts[item] = fail_counts.get(item, 0) + 1

                consecutive_fails = self._find_consecutive_fails(signals)

                summary = {
                    "total": total,
                    "passed": passed,
                    "failed": total - passed,
                    "pass_rate": round(passed / total * 100, 1) if total else 0,
                    "fail_distribution": fail_counts,
                    "consecutive_fails": consecutive_fails,
                }
                return json.dumps(summary, ensure_ascii=False, indent=2)

            return f"Error: unknown action '{action}'"

        except Exception as e:
            logger.error(f"quality_signal failed: {e}")
            return f"Error: {e}"

    @staticmethod
    def _find_consecutive_fails(signals: list) -> Dict[str, int]:
        """找出每个质量维度连续不通过的最大次数。"""
        if not signals:
            return {}

        all_dims = set()
        for s in signals:
            all_dims.update(s.get("quality", {}).get("fail_items", []))

        result = {}
        for dim in all_dims:
            max_streak = 0
            current = 0
            for s in reversed(signals):
                if dim in s.get("quality", {}).get("fail_items", []):
                    current += 1
                    max_streak = max(max_streak, current)
                else:
                    current = 0
            if max_streak >= 2:
                result[dim] = max_streak
        return result
