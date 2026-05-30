"""
Command Parser — Intent detection & NL → shell translation
The invisible layer that reads between the lines.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("command_parser")


@dataclass
class ParsedIntent:
    intent: str           # "command" | "chat" | "confused"
    confidence: float     # 0.0–1.0
    command: Optional[str] = None      # Raw shell command if intent == "command"
    action: Optional[str] = None       # High-level action label
    needs_confirm: bool = False
    raw: str = ""
    metadata: dict = field(default_factory=dict)


# ── Intent Patterns ────────────────────────────────────────────────────────

COMMAND_PATTERNS = [
    # File operations
    (r"(?:create|make|write|new)\s+(?:a\s+)?file\s+(?:called\s+|named\s+)?(.+?)(?:\s+with\s+(?:content\s+)?(.+))?$",
     "create_file"),
    (r"(?:show|list|ls|display)\s+(?:files?|dir|directory|folder)(?:\s+in\s+(.+))?",
     "list_files"),
    (r"(?:read|show|cat|display|print)\s+(?:file\s+|contents?\s+of\s+)?(.+\.[\w]+)",
     "read_file"),

    # System info
    (r"(?:check|show|get|display)\s+(?:my\s+)?(?:disk\s+(?:space|usage)|storage)",
     "disk_space"),
    (r"(?:check|show|get|display)\s+(?:my\s+)?(?:ram|memory|mem)",
     "memory"),
    (r"(?:check|show|what'?s?)\s+(?:the\s+)?(?:system\s+)?(?:status|health)",
     "system_status"),
    (r"(?:running\s+processes?|show\s+processes?|ps|what'?s?\s+running)",
     "processes"),
    (r"(?:check|show|what'?s?)\s+(?:the\s+)?(?:uptime|up\s+time)",
     "uptime"),
    (r"(?:check|show|display)\s+(?:network|connections?|ports?)",
     "network"),

    # Git
    (r"(?:git\s+(?:status|log|diff|branch|pull|push|commit|add|clone).*)",
     "git"),

    # Directory ops
    (r"(?:create|make|mkdir)\s+(?:a\s+)?(?:directory|dir|folder)\s+(?:called\s+|named\s+)?(.+)",
     "mkdir"),

    # Find / search
    (r"(?:find|search\s+for)\s+(?:file\s+)?(.+?)(?:\s+in\s+(.+))?$",
     "find_file"),

    # Process
    # TODO: the leading "do" alternative over-matches conversational phrases
    # like "do you remember my name?" and routes them to command/execute
    # instead of chat. Tighten this (e.g. require "do" to be followed by a
    # verb, or drop it) without breaking "do <cmd>" usage. Left as-is here to
    # avoid changing routing behavior in a hygiene-only pass.
    (r"(?:run|execute|do)\s+(.+)",
     "execute"),

    # Ollama
    (r"(?:ask\s+ollama|local\s+ai|ollama)\s+(.+)",
     "ollama"),
]

DESTRUCTIVE_ACTIONS = {"delete_file", "move_file", "overwrite_file"}

CHAT_SIGNALS = [
    r"^(?:hi|hello|hey|sup|yo|what'?s?\s+up)",
    r"^(?:how\s+are\s+you|how'?re\s+you)",
    r"^(?:thanks?|thank\s+you|thx|ty)",
    r"^(?:ok|okay|cool|got\s+it|nice|great|perfect)",
    r"^(?:yes|no|yeah|yep|nope|nah)",
    r"^(?:bye|goodbye|cya|later|see\s+ya)",
    r"\?$",  # Questions ending with ?
]


def parse(message: str) -> ParsedIntent:
    """
    Main entry point. Returns ParsedIntent routing the message.
    """
    msg = message.strip()
    msg_lower = msg.lower()

    # ── Check for command intent ───────────────────────────────────────────
    for pattern, action in COMMAND_PATTERNS:
        match = re.search(pattern, msg_lower, re.IGNORECASE)
        if match:
            cmd = _build_command(action, match, msg)
            needs_confirm = action in DESTRUCTIVE_ACTIONS
            return ParsedIntent(
                intent="command",
                confidence=0.9,
                command=cmd,
                action=action,
                needs_confirm=needs_confirm,
                raw=msg,
                metadata={"groups": match.groups()},
            )

    # ── Check for chat signals ─────────────────────────────────────────────
    for pattern in CHAT_SIGNALS:
        if re.search(pattern, msg_lower):
            return ParsedIntent(
                intent="chat",
                confidence=0.85,
                raw=msg,
            )

    # ── Heuristic: short messages are probably chat ───────────────────────
    if len(msg.split()) <= 4:
        return ParsedIntent(intent="chat", confidence=0.6, raw=msg)

    # ── Long, unrecognized message → confused ────────────────────────────
    return ParsedIntent(
        intent="confused",
        confidence=0.5,
        raw=msg,
    )


def _build_command(action: str, match: re.Match, original: str) -> Optional[str]:
    """Translate parsed intent into a shell command string."""
    groups = match.groups()

    if action == "list_files":
        path = groups[0].strip() if groups and groups[0] else "."
        return f"ls -la {path}"

    if action == "disk_space":
        return "df -h"

    if action == "memory":
        return "free -h"

    if action == "system_status":
        return "uptime && free -h && df -h /"

    if action == "processes":
        return "ps aux --sort=-%cpu | head -20"

    if action == "uptime":
        return "uptime"

    if action == "network":
        return "ss -tulnp"

    if action == "read_file":
        filename = groups[0].strip() if groups and groups[0] else ""
        return f"cat {filename}" if filename else None

    if action == "find_file":
        name = groups[0].strip() if groups and groups[0] else ""
        path = groups[1].strip() if len(groups) > 1 and groups[1] else "."
        return f"find {path} -name '*{name}*' 2>/dev/null | head -20"

    if action == "mkdir":
        dirname = groups[0].strip() if groups and groups[0] else ""
        return f"mkdir -p {dirname}" if dirname else None

    if action == "git":
        # Pass git commands through directly. Match case-insensitively but
        # capture from the ORIGINAL string so argument casing is preserved
        # (e.g. branch names, commit messages must not be lowercased).
        git_match = re.search(r"(git\s+\w+.*)", original, re.IGNORECASE)
        return git_match.group(1) if git_match else None

    if action == "execute":
        # Raw execute - pass through with safety check in shell_ghost
        return groups[0].strip() if groups and groups[0] else None

    if action == "ollama":
        prompt = groups[0].strip() if groups and groups[0] else original
        return f'ollama run llama3 "{prompt}"'

    return None


def extract_file_create_params(message: str) -> Optional[dict]:
    """
    Extract filename and content from file creation messages.
    Returns None if can't parse.
    """
    # Pattern: create file X with content Y
    match = re.search(
        r"(?:create|make|write)\s+(?:a\s+)?file\s+"
        r"(?:called\s+|named\s+)?[\"']?([^\s\"']+)[\"']?"
        r"(?:\s+with\s+(?:content\s+)?[\"']?(.+?)[\"']?)?$",
        message,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return {
            "path": match.group(1),
            "content": match.group(2) or "",
        }
    return None
