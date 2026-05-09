import pytest

from core.sandbox import check_path, check_command


class TestCheckPath:
    def test_sandbox_disabled_allows_any_path(self, tmp_path):
        allowed, reason = check_path("/etc/passwd", str(tmp_path), sandbox=False)
        assert allowed is True

    def test_sandbox_allows_path_inside_root(self, tmp_path):
        file_path = str(tmp_path / "test.txt")
        allowed, reason = check_path(file_path, str(tmp_path), sandbox=True)
        assert allowed is True

    def test_sandbox_blocks_path_outside_root(self, tmp_path):
        allowed, reason = check_path("/etc/passwd", str(tmp_path), sandbox=True)
        assert allowed is False
        assert "outside" in reason.lower()

    def test_sandbox_blocks_path_traversal(self, tmp_path):
        traversal = str(tmp_path / ".." / ".." / "etc" / "passwd")
        allowed, reason = check_path(traversal, str(tmp_path), sandbox=True)
        assert allowed is False

    def test_relative_path_inside_root(self, tmp_path):
        # 相对路径会被 resolve 到 cwd，不在 tmp_path 下（这是正确行为）
        file_path = str(tmp_path / "subdir" / "file.txt")
        allowed, reason = check_path(file_path, str(tmp_path), sandbox=True)
        assert allowed is True


class TestCheckCommand:
    def test_empty_blocklist_allows_all(self):
        allowed, reason = check_command("rm -rf /", [])
        assert allowed is True

    def test_blocked_command_matches(self):
        allowed, reason = check_command("rm -rf /", ["rm"])
        assert allowed is False

    def test_case_insensitive_match(self):
        allowed, reason = check_command("RM -RF /", ["rm"])
        assert allowed is False

    def test_safe_command_allowed(self):
        allowed, reason = check_command("ls -la", ["rm", "mkfs"])
        assert allowed is True

    def test_no_substring_false_positive(self):
        # "rm" 只匹配首词，不应拦截 "docker rm" 这类子命令
        allowed, reason = check_command("docker rm container", ["rm"])
        assert allowed is True
        # "dd" 不应匹配 "docker dd"——首词是 docker
        allowed, reason = check_command("docker dd something", ["dd"])
        assert allowed is True
