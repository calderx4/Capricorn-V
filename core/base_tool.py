"""
BaseTool - 工具抽象基类

定义工具的统一接口，包括：
- JSON Schema 参数定义
- 参数类型转换与验证
- 转换为 LangChain StructuredTool 格式
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple, Union, get_origin, get_args
from loguru import logger


class BaseTool(ABC):
    """工具抽象基类"""

    auto_discover = True

    @classmethod
    def from_config(cls, config: dict) -> "BaseTool":
        """从配置创建实例，需要外部依赖的子类覆写此方法"""
        return cls()

    # JSON Schema 类型到 Python 类型的映射
    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": float,  # 使用 float 而不是 (int, float)，兼容 Pydantic
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    @property
    @abstractmethod
    def name(self) -> str:
        """
        工具名称

        Returns:
            工具的唯一标识符
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """
        工具描述

        Returns:
            工具的功能说明
        """
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """
        JSON Schema 参数定义

        Returns:
            JSON Schema 格式的参数定义
        """
        pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """
        执行工具

        Args:
            **kwargs: 工具参数

        Returns:
            执行结果
        """
        pass

    def to_langchain_tool(self):
        """
        转换为 LangChain 工具格式

        Returns:
            LangChain StructuredTool 实例
        """
        from langchain_core.tools import StructuredTool
        from pydantic import create_model

        # 从 JSON Schema 创建 Pydantic 模型
        field_definitions = {}
        properties = self.parameters.get("properties", {})
        required = self.parameters.get("required", [])

        for field_name, field_schema in properties.items():
            field_type = self._json_schema_to_python_type(field_schema)
            default = ... if field_name in required else None
            field_definitions[field_name] = (field_type, default)

        args_schema = create_model(f"{self.name}Args", **field_definitions)

        return StructuredTool(
            name=self.name,
            description=self.description,
            args_schema=args_schema,
            coroutine=self.execute,
        )

    def _json_schema_to_python_type(self, schema: Dict[str, Any]) -> type:
        """
        将 JSON Schema 类型转换为 Python 类型

        Args:
            schema: JSON Schema 定义

        Returns:
            Python 类型
        """
        json_type = schema.get("type", "string")

        if json_type == "array":
            items = schema.get("items", {})
            item_type = self._json_schema_to_python_type(items)
            return List[item_type]

        if json_type == "object":
            # 简化处理：object 类型映射为 Dict
            return Dict[str, Any]

        return self._TYPE_MAP.get(json_type, str)

    def cast_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        参数类型转换

        根据 JSON Schema 定义，将参数转换为正确的类型。

        Args:
            params: 原始参数字典

        Returns:
            类型转换后的参数字典
        """
        if not params:
            return params

        properties = self.parameters.get("properties", {})
        casted = {}

        for key, value in params.items():
            if key not in properties:
                # 未知参数，保持原样
                casted[key] = value
                continue

            schema = properties[key]
            json_type = schema.get("type", "string")

            try:
                casted[key] = self._cast_value(value, json_type, schema)
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to cast parameter '{key}': {e}, using original value")
                casted[key] = value

        return casted

    def _cast_value(self, value: Any, json_type: str, schema: Dict[str, Any]) -> Any:
        """
        转换单个值

        Args:
            value: 原始值
            json_type: JSON Schema 类型
            schema: 完整的 schema 定义

        Returns:
            转换后的值
        """
        if value is None:
            return None

        if json_type == "string":
            return str(value)

        if json_type == "integer":
            return int(value)

        if json_type == "number":
            # 尝试转换为 int 或 float
            if isinstance(value, int):
                return value
            return float(value)

        if json_type == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)

        if json_type == "array":
            if isinstance(value, list):
                # 递归转换数组元素
                items_schema = schema.get("items", {})
                items_type = items_schema.get("type", "string")
                return [
                    self._cast_value(item, items_type, items_schema)
                    for item in value
                ]
            # 单个值转换为数组
            return [value]

        if json_type == "object":
            if isinstance(value, dict):
                return value
            # 尝试解析 JSON 字符串
            if isinstance(value, str):
                import json
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    pass
            return value

        # 未知类型，保持原样
        return value

    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """
        参数验证

        检查参数是否符合 JSON Schema 定义。

        Args:
            params: 参数字典

        Returns:
            错误消息列表（空列表表示验证通过）
        """
        errors = []
        properties = self.parameters.get("properties", {})
        required = self.parameters.get("required", [])

        # 检查必需参数
        for param_name in required:
            if param_name not in params:
                errors.append(f"Missing required parameter: {param_name}")

        # 检查参数类型
        for param_name, param_value in params.items():
            if param_name not in properties:
                # 允许额外参数，但记录警告
                logger.debug(f"Unknown parameter: {param_name}")
                continue

            schema = properties[param_name]
            json_type = schema.get("type", "string")

            if not self._validate_type(param_value, json_type, schema):
                errors.append(
                    f"Parameter '{param_name}' has wrong type: expected {json_type}, "
                    f"got {type(param_value).__name__}"
                )

        return errors

    def _validate_type(self, value: Any, json_type: str, schema: Dict[str, Any]) -> bool:
        """
        验证值的类型

        Args:
            value: 待验证的值
            json_type: JSON Schema 类型
            schema: 完整的 schema 定义

        Returns:
            是否通过验证
        """
        if value is None:
            # None 值允许（除非有额外约束）
            return True

        if json_type == "string":
            return isinstance(value, str)

        if json_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)

        if json_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)

        if json_type == "boolean":
            return isinstance(value, bool)

        if json_type == "array":
            if not isinstance(value, list):
                return False
            # 递归验证数组元素
            items_schema = schema.get("items", {})
            items_type = items_schema.get("type", "string")
            return all(
                self._validate_type(item, items_type, items_schema)
                for item in value
            )

        if json_type == "object":
            if not isinstance(value, dict):
                return False
            # 可以进一步验证 object 的 properties
            return True

        # 未知类型，默认通过
        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}')>"
