import pytest
from typing import Any, Dict

from core.base_tool import BaseTool


class _DummyTool(BaseTool):
    """测试用工具"""

    @property
    def name(self) -> str:
        return "dummy_tool"

    @property
    def description(self) -> str:
        return "A tool for testing"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {"type": "integer", "description": "Result count"},
                "verbose": {"type": "boolean"},
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs):
        return f"executed with {kwargs}"


class _NoParamsTool(BaseTool):
    """无参数工具"""

    @property
    def name(self) -> str:
        return "no_params"

    @property
    def description(self) -> str:
        return "No params"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs):
        return "ok"


class TestBaseToolAbstract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseTool()


class TestBaseToolProperties:
    def setup_method(self):
        self.tool = _DummyTool()

    def test_name(self):
        assert self.tool.name == "dummy_tool"

    def test_description(self):
        assert self.tool.description == "A tool for testing"

    def test_parameters_schema(self):
        schema = self.tool.parameters
        assert "properties" in schema
        assert "query" in schema["properties"]
        assert schema["required"] == ["query"]


class TestParamValidation:
    def setup_method(self):
        self.tool = _DummyTool()

    def test_valid_params(self):
        errors = self.tool.validate_params({"query": "hello", "count": 5})
        assert errors == []

    def test_missing_required(self):
        errors = self.tool.validate_params({"count": 5})
        assert len(errors) == 1
        assert "query" in errors[0]

    def test_wrong_type(self):
        errors = self.tool.validate_params({"query": "hello", "count": "not-int"})
        assert len(errors) == 1
        assert "count" in errors[0]

    def test_unknown_param_allowed(self):
        errors = self.tool.validate_params({"query": "hello", "extra": "val"})
        assert errors == []


class TestParamCasting:
    def setup_method(self):
        self.tool = _DummyTool()

    def test_string_cast(self):
        result = self.tool.cast_params({"query": 123})
        assert result["query"] == "123"
        assert isinstance(result["query"], str)

    def test_integer_cast(self):
        result = self.tool.cast_params({"count": "42"})
        assert result["count"] == 42

    def test_boolean_cast(self):
        result = self.tool.cast_params({"verbose": "true"})
        assert result["verbose"] is True

    def test_empty_params(self):
        result = self.tool.cast_params({})
        assert result == {}


class TestRepr:
    def test_repr_format(self):
        tool = _DummyTool()
        assert repr(tool) == "<_DummyTool(name='dummy_tool')>"
