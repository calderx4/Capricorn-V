"""
Core utilities - 共享工具函数
"""

import os
import re
import tempfile
from pathlib import Path


def strip_thinking_tags(text: str) -> str:
    """移除 <thinking>...</thinking> 标签及其内容"""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", text, flags=re.DOTALL).strip()


def atomic_write(path: Path, content: str) -> None:
    """原子写入：先写临时文件，再 rename 替换。防止崩溃时截断。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
