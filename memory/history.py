"""
History Log - 历史日志管理

职责：
- 管理 HISTORY.md 文件
- 追加时间线记录
- 提供搜索接口
"""

from typing import List
from loguru import logger

from config.settings import WorkspaceConfig


class HistoryLog:
    """历史日志管理"""

    def __init__(self, workspace: WorkspaceConfig):
        """
        初始化历史日志管理器

        Args:
            workspace: 工作空间配置
        """
        self.file_path = workspace.get_memory_path("HISTORY.md")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(f"History log path: {self.file_path}")

    def append(self, entry: str) -> None:
        """
        追加历史记录

        Args:
            entry: 历史记录条目（建议格式：[YYYY-MM-DD HH:MM] 事件描述）
        """
        try:
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
            logger.debug(f"Appended to history log: {entry[:50]}...")
        except Exception as e:
            logger.error(f"Failed to append to history log: {e}")
            raise

    def read(self, limit: int = None) -> List[str]:
        """
        读取历史记录

        Args:
            limit: 限制读取条数（None 表示全部）

        Returns:
            历史记录列表
        """
        if not self.file_path.exists():
            return []

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]

            if limit:
                lines = lines[-limit:]

            return lines
        except Exception as e:
            logger.error(f"Failed to read history log: {e}")
            return []

    def search(self, query: str, case_sensitive: bool = False) -> List[str]:
        """
        搜索历史记录

        Args:
            query: 搜索关键词
            case_sensitive: 是否区分大小写

        Returns:
            匹配的历史记录列表
        """
        if not self.file_path.exists():
            return []

        try:
            results = []
            search_query = query if case_sensitive else query.lower()

            with open(self.file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_stripped = line.strip()
                    if not line_stripped:
                        continue

                    search_line = line_stripped if case_sensitive else line_stripped.lower()

                    if search_query in search_line:
                        results.append(line_stripped)

            logger.debug(f"History search for '{query}': found {len(results)} results")
            return results
        except Exception as e:
            logger.error(f"Failed to search history log: {e}")
            return []

    def exists(self) -> bool:
        """检查历史日志文件是否存在"""
        return self.file_path.exists()

    def count(self) -> int:
        """获取历史记录条数"""
        if not self.file_path.exists():
            return 0

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except Exception as e:
            logger.error(f"Failed to count history log: {e}")
            return 0
