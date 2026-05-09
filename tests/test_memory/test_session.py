import json
import pytest
from pathlib import Path

from config.settings import WorkspaceConfig
from memory.session import Session, SessionManager, _serialize_message


class TestSession:
    def test_add_message(self):
        session = Session(thread_id="test")
        session.add_message("user", "hello")
        assert len(session.messages) == 1
        assert session.messages[0]["role"] == "user"
        assert session.messages[0]["content"] == "hello"

    def test_add_message_with_kwargs(self):
        session = Session(thread_id="test")
        session.add_message("assistant", "done", tools_used=["echo"])
        assert session.messages[0]["tools_used"] == ["echo"]

    def test_get_history_all(self):
        session = Session(thread_id="test")
        for i in range(5):
            session.add_message("user", f"msg {i}")
        history = session.get_history()
        assert len(history) == 5

    def test_get_history_limited(self):
        session = Session(thread_id="test")
        for i in range(10):
            session.add_message("user", f"msg {i}")
        history = session.get_history(max_messages=3)
        assert len(history) == 3
        assert history[0]["content"] == "msg 7"


class TestSessionManager:
    def _make_workspace(self, tmp_path):
        return WorkspaceConfig(root=str(tmp_path), session_dir="sessions")

    def test_creates_session_dir(self, tmp_path):
        ws = self._make_workspace(tmp_path)
        SessionManager(ws)
        assert (tmp_path / "sessions").is_dir()

    def test_get_new_session(self, tmp_path):
        mgr = SessionManager(self._make_workspace(tmp_path))
        session = mgr.get_session("new-thread")
        assert session.thread_id == "new-thread"
        assert len(session.messages) == 0

    def test_save_and_load(self, tmp_path):
        mgr = SessionManager(self._make_workspace(tmp_path))
        session = mgr.get_session("test")
        session.add_message("user", "hello")
        session.add_message("assistant", "world")

        mgr.save_session(session)

        loaded = mgr.load_session("test")
        assert loaded is not None
        assert len(loaded.messages) == 2
        assert loaded.messages[0]["content"] == "hello"
        assert loaded.messages[1]["content"] == "world"

    def test_load_nonexistent(self, tmp_path):
        mgr = SessionManager(self._make_workspace(tmp_path))
        assert mgr.load_session("ghost") is None

    def test_clear_session(self, tmp_path):
        mgr = SessionManager(self._make_workspace(tmp_path))
        session = mgr.get_session("to-clear")
        session.add_message("user", "bye")
        mgr.save_session(session)

        mgr.clear_session("to-clear")
        assert mgr.load_session("to-clear") is None

    def test_session_persists_jsonl_format(self, tmp_path):
        mgr = SessionManager(self._make_workspace(tmp_path))
        session = mgr.get_session("jsonl-test")
        session.add_message("user", "test content")
        mgr.save_session(session)

        session_file = tmp_path / "sessions" / "jsonl-test.jsonl"
        assert session_file.exists()
        lines = session_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["role"] == "user"
        assert data["content"] == "test content"

    def test_save_preserves_tool_calls(self, tmp_path):
        mgr = SessionManager(self._make_workspace(tmp_path))
        session = mgr.get_session("tc-test")
        session.add_message("assistant", "",
                            tool_calls=[{"id": "call_1", "name": "read_file", "args": {"path": "x"}}])
        session.add_message("tool", "file content", tool_call_id="call_1")

        mgr.save_session(session)
        loaded = mgr.load_session("tc-test")
        assert loaded is not None
        assert len(loaded.messages) == 2
        assert loaded.messages[0]["tool_calls"] is not None
        assert loaded.messages[0]["tool_calls"][0]["name"] == "read_file"
        assert loaded.messages[1]["role"] == "tool"
        assert loaded.messages[1]["tool_call_id"] == "call_1"

    def test_rewrite_session_preserves_structural_messages(self, tmp_path):
        mgr = SessionManager(self._make_workspace(tmp_path))
        session = mgr.get_session("rewrite-test")
        session.add_message("user", "hello")
        # AI message with tool_calls but empty content
        session.add_message("assistant", "",
                            tool_calls=[{"id": "c1", "name": "read_file", "args": {}}])
        session.add_message("tool", "result", tool_call_id="c1")

        mgr.save_session(session)
        loaded = mgr.load_session("rewrite-test")
        assert loaded is not None
        # tool_calls message should be preserved even though content is empty
        assert len(loaded.messages) == 3


class TestSerializeMessage:
    def test_normal_message(self):
        msg = {"role": "user", "content": "hello"}
        result = _serialize_message(msg)
        assert "hello" in result
        assert result.endswith("\n")

    def test_tool_calls_message_preserved(self):
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "name": "read_file", "args": {}}]
        }
        result = _serialize_message(msg)
        assert result != ""  # 不被丢弃
        data = json.loads(result)
        assert "tool_calls" in data

    def test_tool_message_preserved(self):
        msg = {"role": "tool", "content": "result", "tool_call_id": "c1"}
        result = _serialize_message(msg)
        data = json.loads(result)
        assert data["tool_call_id"] == "c1"

    def test_empty_message_dropped(self):
        msg = {"role": "assistant", "content": ""}
        result = _serialize_message(msg)
        assert result == ""

    def test_thinking_tags_stripped(self):
        msg = {"role": "assistant", "content": "<thinking>inner</thinking>response"}
        result = _serialize_message(msg)
        data = json.loads(result)
        assert "<thinking>" not in data["content"]
        assert "response" in data["content"]
