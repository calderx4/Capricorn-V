"""
Long Term Memory - 长期记忆管理

职责：
- 管理 MEMORY.md 文件
- 提供读写接口
"""

import os
import tempfile
from loguru import logger

from config.settings import WorkspaceConfig


class LongTermMemory:
    """长期记忆管理"""

    def __init__(self, workspace: WorkspaceConfig):
        """
        初始化长期记忆管理器

        Args:
            workspace: 工作空间配置
        """
        self.file_path = workspace.get_memory_path("MEMORY.md")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Long term memory path: {self.file_path}")

    def read(self) -> str:
        """
        读取长期记忆

        Returns:
            长期记忆内容（空字符串表示无记忆）
        """
        if not self.file_path.exists():
            return ""

        try:
            content = self.file_path.read_text(encoding="utf-8")
            logger.debug(f"Read long term memory: {len(content)} chars")
            return content
        except Exception as e:
            logger.error(f"Failed to read long term memory: {e}")
            return ""

    def write(self, content: str) -> None:
        """原子写入长期记忆。"""
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=self.file_path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp_path, self.file_path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            logger.debug(f"Wrote long term memory: {len(content)} chars")
        except Exception as e:
            logger.error(f"Failed to write long term memory: {e}")
            raise

    def append(self, content: str) -> None:
        """
        追加内容到长期记忆

        Args:
            content: 要追加的内容
        """
        try:
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(content + "\n")
            logger.debug(f"Appended to long term memory: {len(content)} chars")
        except Exception as e:
            logger.error(f"Failed to append to long term memory: {e}")
            raise

    def exists(self) -> bool:
        """检查长期记忆文件是否存在"""
        return self.file_path.exists()
