"""
Exec Tools - 终端执行工具

提供 shell 命令执行功能。
sandbox=True 时 cwd 和路径参数限制在 workspace 内。
blocked_commands 配置项独立于 sandbox，始终生效。
"""

import asyncio
from typing import Any, Dict, List
from loguru import logger

from core.base_tool import BaseTool
from core.sandbox import check_path, check_command


class ExecTool(BaseTool):
    """Shell 命令执行工具"""

    MAX_TIMEOUT = 120  # 单条命令最长 120 秒

    def __init__(self, workspace_root: str = "./workspace", sandbox: bool = True,
                 blocked_commands: List[str] = None):
        self._workspace_root = workspace_root
        self._sandbox = sandbox
        self._blocked_commands = blocked_commands or []

    @classmethod
    def from_config(cls, config: dict) -> "ExecTool":
        return cls(
            config["workspace_root"],
            config.get("sandbox", True),
            config.get("blocked_commands", []),
        )

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return (
            "执行 shell 命令，返回 stdout/stderr/exit code。适用场景：运行脚本、安装包、git 操作、编译、测试。\n"
            "参数：cwd（工作目录）、timeout（超时秒数，默认30，最大120）。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (optional)"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30)",
                    "default": 30
                }
            },
            "required": ["command"]
        }

    async def execute(self, command: str, cwd: str = None, timeout: int = 30) -> str:
        timeout = min(max(timeout, 1), self.MAX_TIMEOUT)
        # 危险命令检查（独立于 sandbox）
        allowed, reason = check_command(command, self._blocked_commands)
        if not allowed:
            return f"Error: {reason}"

        # 默认 cwd 为 workspace root，sandbox 模式下额外校验路径
        effective_cwd = cwd or self._workspace_root
        if self._sandbox:
            allowed, reason = check_path(effective_cwd, self._workspace_root, True)
            if not allowed:
                return f"Error: {reason}"

        try:
            logger.debug(f"Executing command: {command} (cwd={effective_cwd})")

            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=effective_cwd
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"Error: Command timed out after {timeout} seconds"

            result = []

            if stdout:
                stdout_text = stdout.decode('utf-8', errors='replace')
                if stdout_text.strip():
                    result.append(stdout_text.strip())

            if stderr:
                stderr_text = stderr.decode('utf-8', errors='replace')
                if stderr_text.strip():
                    result.append(f"[stderr] {stderr_text.strip()}")

            output = "\n".join(result)

            if proc.returncode != 0:
                output = f"{output}\n[exit code: {proc.returncode}]"

            logger.debug(f"Command completed with exit code {proc.returncode}")

            return output if output else "(no output)"

        except Exception as e:
            logger.error(f"Failed to execute command '{command}': {e}")
            return f"Error: {str(e)}"
