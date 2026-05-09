"""
BaseWorkflow - 工作流抽象基类

定义工作流的统一接口，包括：
- 声明依赖的工具
- 提供状态和记忆管理接口
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseWorkflow(ABC):
    """工作流抽象基类"""

    auto_discover = True

    @classmethod
    def from_config(cls, config: dict) -> "BaseWorkflow":
        """从配置创建实例，需要外部依赖的子类覆写此方法"""
        return cls()

    @property
    @abstractmethod
    def name(self) -> str:
        """
        工作流名称

        Returns:
            工作流的唯一标识符
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """
        工作流描述

        Returns:
            工作流的功能说明
        """
        pass

    @property
    @abstractmethod
    def required_tools(self) -> List[str]:
        """
        依赖的工具列表

        Returns:
            工具名称列表
        """
        pass

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        """工作流参数 schema，子类可覆写以自定义参数格式"""
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": f"Task description for the {self.name} workflow",
                }
            },
            "required": ["task"],
        }

    @abstractmethod
    async def execute(self, tools: Any, **kwargs: Any) -> Any:
        """
        执行工作流

        Args:
            tools: 工具注册中心实例，用于调用工具
            **kwargs: 工作流参数

        Returns:
            执行结果
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}')>"
