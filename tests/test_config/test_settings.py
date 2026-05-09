import json
import pytest
from pathlib import Path

from config.settings import (
    Config,
    WorkspaceConfig,
    LLMConfig,
    MCPServerConfig,
    MemoryConfig,
)


class TestWorkspaceConfig:
    def test_default_values(self):
        cfg = WorkspaceConfig()
        assert cfg.root == "./workspace"
        assert cfg.memory_dir == "memory"
        assert cfg.session_dir == "sessions"

    def test_custom_root(self):
        cfg = WorkspaceConfig(root="/tmp/capricorn")
        assert cfg.root == "/tmp/capricorn"

    def test_get_memory_path(self, tmp_path):
        cfg = WorkspaceConfig(root=str(tmp_path))
        path = cfg.get_memory_path("MEMORY.md")
        assert path == tmp_path / "memory" / "MEMORY.md"

    def test_get_session_path(self, tmp_path):
        cfg = WorkspaceConfig(root=str(tmp_path))
        path = cfg.get_session_path("default")
        assert path == tmp_path / "sessions" / "default.jsonl"


class TestLLMConfig:
    def test_required_fields(self):
        cfg = LLMConfig(provider="openai", model="test-model", api_key="sk-test")
        assert cfg.provider == "openai"
        assert cfg.model == "test-model"
        assert cfg.temperature == 0.7

    def test_temperature_bounds(self):
        with pytest.raises(Exception):
            LLMConfig(provider="openai", model="test", api_key="sk", temperature=3.0)

    def test_max_tokens_positive(self):
        with pytest.raises(Exception):
            LLMConfig(provider="openai", model="test", api_key="sk", max_tokens=0)


class TestMCPServerConfig:
    def test_stdio_type(self):
        cfg = MCPServerConfig(type="stdio", command="npx", args=["-y", "some-server"])
        assert cfg.enabled is True
        assert cfg.tool_timeout == 30

    def test_sse_type(self):
        cfg = MCPServerConfig(
            type="sse",
            url="http://localhost:8080/sse",
            headers={"Authorization": "Bearer test"},
        )
        assert cfg.url == "http://localhost:8080/sse"


class TestConfigLoad:
    def _write_config(self, tmp_path, data):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(data), encoding="utf-8")
        return str(config_path)

    def test_load_minimal(self, tmp_path):
        path = self._write_config(tmp_path, {
            "workspace": {"root": str(tmp_path)},
            "llm": {"provider": "openai", "model": "test", "api_key": "sk-test"},
        })
        config = Config.load(path)
        assert config.llm.provider == "openai"
        assert config.workspace.root == str(tmp_path)

    def test_load_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            Config.load("/nonexistent/config.json")

    def test_load_with_mcp_servers(self, tmp_path):
        path = self._write_config(tmp_path, {
            "workspace": {"root": str(tmp_path)},
            "llm": {"provider": "openai", "model": "test", "api_key": "sk"},
            "mcp_servers": {
                "test": {"type": "stdio", "command": "test-cmd", "enabled": False},
            },
        })
        config = Config.load(path)
        assert "test" in config.mcp_servers
        assert config.mcp_servers["test"].enabled is False

    def test_repr(self, tmp_path):
        path = self._write_config(tmp_path, {
            "workspace": {"root": str(tmp_path)},
            "llm": {"provider": "anthropic", "model": "claude", "api_key": "sk"},
        })
        config = Config.load(path)
        assert "anthropic" in repr(config)
