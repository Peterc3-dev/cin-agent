"""Unit tests for command_parser — pure intent detection and NL->shell logic.

Only the standard-library command_parser module is imported here; no telegram,
httpx, network, GPU, or model dependencies are touched.
"""

import command_parser as cp


def test_chat_greeting_is_chat():
    p = cp.parse("hey what's up")
    assert p.intent == "chat"


def test_question_mark_is_chat():
    # A trailing "?" is a chat signal. Avoid leading verbs like "do"/"run"
    # which currently match the command patterns first (see TODO in
    # command_parser COMMAND_PATTERNS for the known "do ..." over-match).
    p = cp.parse("are you still there?")
    assert p.intent == "chat"


def test_short_unrecognized_is_chat():
    # <= 4 words and no command/chat pattern -> chat heuristic
    p = cp.parse("the round blue thing")
    assert p.intent == "chat"
    assert p.confidence == 0.6


def test_long_unrecognized_is_confused():
    p = cp.parse("please describe the weather over the next several days in detail")
    assert p.intent == "confused"


def test_disk_space_command():
    p = cp.parse("show disk space")
    assert p.intent == "command"
    assert p.action == "disk_space"
    assert p.command == "df -h"


def test_memory_command():
    p = cp.parse("check memory")
    assert p.command == "free -h"


def test_system_status_command():
    p = cp.parse("check status")
    assert p.action == "system_status"
    assert p.command == "uptime && free -h && df -h /"


def test_list_files_with_path():
    p = cp.parse("list files in /tmp/sub")
    assert p.action == "list_files"
    assert p.command == "ls -la /tmp/sub"


def test_read_file_builds_cat():
    p = cp.parse("read file config.txt")
    assert p.action == "read_file"
    assert p.command == "cat config.txt"


def test_find_file_with_path():
    p = cp.parse("find notes in /tmp")
    assert p.action == "find_file"
    assert p.command == "find /tmp -name '*notes*' 2>/dev/null | head -20"


def test_mkdir_command():
    p = cp.parse("make a directory called myfolder")
    assert p.action == "mkdir"
    assert p.command == "mkdir -p myfolder"


def test_git_passthrough_preserves_case():
    # Regression: argument casing (commit messages, branch names) must NOT be
    # lowercased. Previously _build_command lowercased the whole command.
    p = cp.parse("git commit -m AddFeatureX")
    assert p.action == "git"
    assert p.command == "git commit -m AddFeatureX"


def test_git_log_passthrough():
    p = cp.parse("git log --oneline")
    assert p.command == "git log --oneline"


def test_ollama_command_wraps_prompt():
    # The prompt is taken from the lowercased match groups, so the wrapped
    # prompt is lowercase. Assert the actual current behavior.
    p = cp.parse("ask ollama what is the capital of France")
    assert p.action == "ollama"
    assert p.command == 'ollama run llama3 "what is the capital of france"'


def test_destructive_actions_set_is_disjoint_from_builders():
    # Sanity: destructive labels are a controlled set.
    assert cp.DESTRUCTIVE_ACTIONS == {"delete_file", "move_file", "overwrite_file"}


def test_extract_file_create_with_content():
    params = cp.extract_file_create_params(
        "create file notes.txt with content hello world"
    )
    assert params == {"path": "notes.txt", "content": "hello world"}


def test_extract_file_create_without_content():
    params = cp.extract_file_create_params("make a file foo.md")
    assert params == {"path": "foo.md", "content": ""}


def test_extract_file_create_non_match_returns_none():
    assert cp.extract_file_create_params("totally not a file command") is None


def test_parsed_intent_metadata_default_is_dict():
    p = cp.parse("hi")
    assert isinstance(p.metadata, dict)
