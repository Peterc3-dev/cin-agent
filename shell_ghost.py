"""
Shell Ghost — Safe command execution layer for CIN Agent
Phosphor green aesthetic. No rm -rf here.
"""

import subprocess
import shlex
import logging
import json
import os
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("shell_ghost")

# Matches piping or redirecting into a shell interpreter, e.g.
#   "curl http://x | bash", "wget ... |sh", "... | zsh".
# The literal DANGEROUS_PATTERNS entries only catch the exact "curl | bash"
# spacing; real-world commands include a URL in between, so this regex closes
# that gap regardless of surrounding text or whitespace.
_PIPE_TO_SHELL = re.compile(r"\|\s*(?:bash|sh|zsh|dash|ksh|fish)\b")

# ── Whitelists & Blacklists ────────────────────────────────────────────────

SAFE_COMMANDS = {
    "ls", "ll", "la", "cat", "head", "tail", "echo", "pwd",
    "df", "du", "free", "top", "htop", "ps", "uptime", "uname",
    "whoami", "id", "hostname", "date", "cal", "which", "whereis",
    "find", "grep", "wc", "sort", "uniq", "cut", "awk", "sed",
    "mkdir", "touch", "cp", "mv", "chmod", "stat", "file",
    "ping", "curl", "wget", "nslookup", "dig",
    "python3", "pip", "pip3", "git",
    "systemctl", "journalctl", "lsof", "netstat", "ss",
    "env", "printenv", "set", "export",
    "tar", "zip", "unzip", "gzip", "gunzip",
    "ollama", "nvidia-smi", "lscpu", "lsmem",
}

DANGEROUS_PATTERNS = [
    "rm -rf", "rm -fr", "sudo", "su ",
    "> /dev/", "dd if=", "mkfs",
    ":(){:|:&};:", "fork bomb",
    "chmod 777 /", "chown -R root",
    "wget -O- | bash", "curl | bash", "curl | sh",
    "; reboot", "; shutdown", "&& reboot",
    ">/etc/passwd", ">/etc/shadow",
]

CONFIRM_REQUIRED = [
    "rm ", "rmdir", "mv ", "cp ",  # destructive file ops
    "kill ", "killall", "pkill",   # process termination
    "iptables", "ufw",             # network rules
    "crontab",                     # scheduled tasks
]

AUDIT_LOG = Path(os.getenv("CIN_DATA_DIR", "~/.cin_agent")).expanduser() / "audit.log"


def _audit(cmd: str, result: str, status: str):
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now().isoformat(),
        "cmd": cmd,
        "status": status,
        "result_len": len(result),
    }
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def is_safe(cmd: str) -> tuple[bool, str]:
    """Returns (safe, reason). Reason is empty string if safe."""
    cmd_lower = cmd.strip().lower()

    # Check dangerous patterns first
    for pattern in DANGEROUS_PATTERNS:
        if pattern in cmd_lower:
            return False, f"Blocked pattern detected: `{pattern}`"

    # Block piping/redirecting into a shell interpreter regardless of the
    # text in between (e.g. "curl http://x | bash").
    if _PIPE_TO_SHELL.search(cmd_lower):
        return False, "Blocked: piping into a shell interpreter"

    # Extract base command
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return False, "Could not parse command (unmatched quotes?)"

    if not parts:
        return False, "Empty command"

    base = parts[0].split("/")[-1]  # strip path prefix

    if base not in SAFE_COMMANDS:
        return False, f"`{base}` is not on the whitelist"

    return True, ""


def needs_confirmation(cmd: str) -> bool:
    cmd_lower = cmd.strip().lower()
    return any(p in cmd_lower for p in CONFIRM_REQUIRED)


def execute(cmd: str, timeout: int = 30, dry_run: bool = False) -> dict:
    """
    Execute a shell command safely.
    Returns: {success, output, error, blocked, reason}
    """
    safe, reason = is_safe(cmd)

    if not safe:
        _audit(cmd, "", "BLOCKED")
        return {
            "success": False,
            "output": "",
            "error": reason,
            "blocked": True,
            "reason": reason,
        }

    if dry_run:
        return {
            "success": True,
            "output": f"[DRY RUN] Would execute: {cmd}",
            "error": "",
            "blocked": False,
            "reason": "",
        }

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout.strip()
        error = result.stderr.strip()

        status = "OK" if result.returncode == 0 else f"EXIT_{result.returncode}"
        _audit(cmd, output, status)

        return {
            "success": result.returncode == 0,
            "output": output or error,
            "error": error if result.returncode != 0 else "",
            "blocked": False,
            "reason": "",
            "returncode": result.returncode,
        }

    except subprocess.TimeoutExpired:
        _audit(cmd, "", "TIMEOUT")
        return {
            "success": False,
            "output": "",
            "error": f"Command timed out after {timeout}s",
            "blocked": False,
            "reason": "",
        }
    except Exception as e:
        _audit(cmd, "", f"ERROR: {e}")
        return {
            "success": False,
            "output": "",
            "error": str(e),
            "blocked": False,
            "reason": "",
        }


def create_file(path: str, content: str, overwrite: bool = False) -> dict:
    """Safe file creation."""
    target = Path(path).expanduser()

    if target.exists() and not overwrite:
        return {
            "success": False,
            "error": f"File `{path}` already exists. Confirm overwrite?",
            "needs_confirm": True,
        }

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        _audit(f"create_file:{path}", content[:50], "OK")
        return {"success": True, "path": str(target), "error": ""}
    except Exception as e:
        return {"success": False, "error": str(e)}
