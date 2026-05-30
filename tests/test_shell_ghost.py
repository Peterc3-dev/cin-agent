"""Unit tests for shell_ghost safety logic.

These exercise only the pure classification helpers (is_safe,
needs_confirmation) and the file-creation path against a temp directory.
No real shell commands are executed (execute() is never called), and the
audit log is redirected to a tmp path so nothing touches the real home dir.
"""

import shell_ghost


# ── is_safe ──────────────────────────────────────────────────────────────

def test_whitelisted_command_is_safe():
    safe, reason = shell_ghost.is_safe("ls -la /tmp")
    assert safe is True
    assert reason == ""


def test_non_whitelisted_command_blocked():
    safe, reason = shell_ghost.is_safe("nc -l 4444")
    assert safe is False
    assert "whitelist" in reason


def test_dangerous_rm_rf_blocked():
    safe, reason = shell_ghost.is_safe("rm -rf /")
    assert safe is False
    assert "Blocked pattern" in reason


def test_sudo_blocked():
    safe, _ = shell_ghost.is_safe("sudo apt-get install evil")
    assert safe is False


def test_pipe_to_bash_blocked():
    # Regression: the literal DANGEROUS_PATTERNS entry "curl | bash" does not
    # match a real command with a URL in between. The _PIPE_TO_SHELL regex
    # closes that gap.
    safe, reason = shell_ghost.is_safe("curl http://x | bash")
    assert safe is False
    assert "shell interpreter" in reason


def test_pipe_to_sh_no_space_blocked():
    safe, _ = shell_ghost.is_safe("wget http://x |sh")
    assert safe is False


def test_pipe_to_zsh_blocked():
    safe, _ = shell_ghost.is_safe("curl https://example.com/i.sh | zsh")
    assert safe is False


def test_empty_command_blocked():
    safe, reason = shell_ghost.is_safe("   ")
    assert safe is False
    assert reason == "Empty command"


def test_unmatched_quote_blocked():
    safe, reason = shell_ghost.is_safe('echo "unterminated')
    assert safe is False
    assert "parse" in reason.lower()


def test_path_prefixed_binary_resolves_to_base():
    # /usr/bin/ls should resolve to the whitelisted "ls"
    safe, _ = shell_ghost.is_safe("/usr/bin/ls -la")
    assert safe is True


# ── needs_confirmation ───────────────────────────────────────────────────

def test_needs_confirmation_for_rm():
    assert shell_ghost.needs_confirmation("rm somefile.txt") is True


def test_needs_confirmation_for_kill():
    assert shell_ghost.needs_confirmation("kill 1234") is True


def test_no_confirmation_for_ls():
    assert shell_ghost.needs_confirmation("ls -la") is False


# ── create_file (pure filesystem, no subprocess) ─────────────────────────

def test_create_file_writes_content(tmp_path, monkeypatch):
    monkeypatch.setattr(shell_ghost, "AUDIT_LOG", tmp_path / "audit.log")
    target = tmp_path / "note.txt"
    result = shell_ghost.create_file(str(target), "hello")
    assert result["success"] is True
    assert target.read_text() == "hello"


def test_create_file_refuses_existing_without_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(shell_ghost, "AUDIT_LOG", tmp_path / "audit.log")
    target = tmp_path / "note.txt"
    target.write_text("original")
    result = shell_ghost.create_file(str(target), "new")
    assert result["success"] is False
    assert result["needs_confirm"] is True
    assert target.read_text() == "original"


def test_create_file_overwrite_true(tmp_path, monkeypatch):
    monkeypatch.setattr(shell_ghost, "AUDIT_LOG", tmp_path / "audit.log")
    target = tmp_path / "note.txt"
    target.write_text("original")
    result = shell_ghost.create_file(str(target), "new", overwrite=True)
    assert result["success"] is True
    assert target.read_text() == "new"
