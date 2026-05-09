import os
import json
import pytest

from config.settings import Config


def _write_config(tmp_path, data):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data), encoding="utf-8")
    return str(config_path)


_BASE_CONFIG = {
    "workspace": {"root": "."},
    "llm": {"provider": "openai", "model": "test", "api_key": "static-key"},
}


class TestEnvVarResolution:
    def test_full_replacement(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "resolved-key-123")
        data = {**_BASE_CONFIG, "llm": {
            "provider": "openai", "model": "test", "api_key": "${TEST_API_KEY}",
        }}
        config = Config.load(_write_config(tmp_path, data))
        assert config.llm.api_key == "resolved-key-123"

    def test_embedded_in_string(self, tmp_path, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "abc123")
        data = {**_BASE_CONFIG, "mcp_servers": {
            "test": {"type": "sse", "url": "http://localhost/${API_TOKEN}/sse"},
        }}
        config = Config.load(_write_config(tmp_path, data))
        assert config.mcp_servers["test"].url == "http://localhost/abc123/sse"

    def test_undefined_var_keeps_placeholder(self, tmp_path):
        os.environ.pop("NONEXISTENT_VAR_99999", None)
        data = {**_BASE_CONFIG, "llm": {
            "provider": "openai", "model": "test", "api_key": "${NONEXISTENT_VAR_99999}",
        }}
        config = Config.load(_write_config(tmp_path, data))
        assert config.llm.api_key == "${NONEXISTENT_VAR_99999}"

    def test_nested_env_in_mcp(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_MCP_KEY", "mcp-secret")
        data = {**_BASE_CONFIG, "mcp_servers": {
            "svc": {
                "type": "stdio",
                "command": "test",
                "env": {"API_KEY": "${MY_MCP_KEY}"},
            },
        }}
        config = Config.load(_write_config(tmp_path, data))
        assert config.mcp_servers["svc"].env["API_KEY"] == "mcp-secret"

    def test_no_env_vars_unchanged(self, tmp_path):
        data = {**_BASE_CONFIG}
        config = Config.load(_write_config(tmp_path, data))
        assert config.llm.api_key == "static-key"
