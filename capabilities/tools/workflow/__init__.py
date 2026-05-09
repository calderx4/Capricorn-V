"""
Workflow Tools module - 工作流工具层

将工作流包装为 LangChain Tool，实现三层工具体系：
- builtin: 原子执行
- mcp: 联网中级执行
- workflow: 复杂执行
"""

from .workflow_wrapper import WorkflowToolWrapper

__all__ = ["WorkflowToolWrapper"]
