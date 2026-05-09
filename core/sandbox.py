"""
Sandbox - 沙盒路径校验

sandbox=true 时，所有文件操作和 exec 的路径必须限定在 workspace root 内。
"""

from pathlib import Path


def check_path(path: str, root: str, sandbox: bool) -> tuple[bool, str]:
    """
    检查路径是否在沙盒范围内。

    Returns:
        (allowed, reason) — allowed=True 表示放行，reason 为空。
        allowed=False 表示拒绝，reason 是原因说明。
    """
    if not sandbox:
        return True, ""

    resolved = Path(path).resolve()
    root_resolved = Path(root).resolve()

    try:
        resolved.relative_to(root_resolved)
        return True, ""
    except ValueError:
        return False, f"Path '{path}' is outside workspace '{root}'"


def check_command(command: str, blocked_commands: list[str]) -> tuple[bool, str]:
    """
    检查命令是否在黑名单中。

    Returns:
        (allowed, reason)
    """
    import shlex
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    base = parts[0].lower() if parts else ""
    for blocked in blocked_commands:
        if base == blocked.lower():
            return False, f"Blocked command: '{blocked}'"
    return True, ""
