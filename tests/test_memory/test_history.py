import pytest
from config.settings import WorkspaceConfig
from memory.history import HistoryLog


class TestHistoryLog:
    def _make_history(self, tmp_path):
        ws = WorkspaceConfig(root=str(tmp_path), memory_dir="memory")
        return HistoryLog(ws)

    def test_read_empty(self, tmp_path):
        history = self._make_history(tmp_path)
        assert history.read() == []
        assert not history.exists()

    def test_append_and_read(self, tmp_path):
        history = self._make_history(tmp_path)
        history.append("[2025-01-01 10:00] event one")
        history.append("[2025-01-01 10:01] event two")
        entries = history.read()
        assert len(entries) == 2
        assert "event one" in entries[0]
        assert "event two" in entries[1]

    def test_read_with_limit(self, tmp_path):
        history = self._make_history(tmp_path)
        for i in range(10):
            history.append(f"entry {i}")
        entries = history.read(limit=3)
        assert len(entries) == 3
        assert "entry 7" in entries[0]

    def test_search(self, tmp_path):
        history = self._make_history(tmp_path)
        history.append("deployed version 1.0")
        history.append("fixed bug in auth")
        history.append("deployed version 1.1")

        results = history.search("deployed")
        assert len(results) == 2

    def test_search_case_insensitive(self, tmp_path):
        history = self._make_history(tmp_path)
        history.append("Deployed Version 1.0")
        results = history.search("deployed")
        assert len(results) == 1

    def test_search_case_sensitive(self, tmp_path):
        history = self._make_history(tmp_path)
        history.append("Deployed Version 1.0")
        results = history.search("deployed", case_sensitive=True)
        assert len(results) == 0

    def test_count(self, tmp_path):
        history = self._make_history(tmp_path)
        assert history.count() == 0
        history.append("a")
        history.append("b")
        assert history.count() == 2

    def test_exists(self, tmp_path):
        history = self._make_history(tmp_path)
        assert not history.exists()
        history.append("test")
        assert history.exists()
