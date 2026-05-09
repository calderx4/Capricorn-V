import pytest
from config.settings import WorkspaceConfig
from memory.long_term import LongTermMemory


class TestLongTermMemory:
    def _make_memory(self, tmp_path):
        ws = WorkspaceConfig(root=str(tmp_path), memory_dir="memory")
        return LongTermMemory(ws)

    def test_read_empty(self, tmp_path):
        mem = self._make_memory(tmp_path)
        assert mem.read() == ""

    def test_write_and_read(self, tmp_path):
        mem = self._make_memory(tmp_path)
        mem.write("# My Memory\n\n- item1\n- item2")
        content = mem.read()
        assert "item1" in content
        assert "item2" in content

    def test_append(self, tmp_path):
        mem = self._make_memory(tmp_path)
        mem.write("first line")
        mem.append("second line")
        content = mem.read()
        assert "first line" in content
        assert "second line" in content

    def test_overwrite(self, tmp_path):
        mem = self._make_memory(tmp_path)
        mem.write("old content")
        mem.write("new content")
        assert mem.read() == "new content"

    def test_exists(self, tmp_path):
        mem = self._make_memory(tmp_path)
        assert not mem.exists()
        mem.write("something")
        assert mem.exists()

    def test_creates_memory_dir(self, tmp_path):
        mem = self._make_memory(tmp_path)
        mem.write("test")
        assert (tmp_path / "memory").is_dir()
        assert (tmp_path / "memory" / "MEMORY.md").exists()
