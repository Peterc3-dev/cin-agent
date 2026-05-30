"""Unit tests for memory — JSON-backed persistent context.

The module computes its file paths at import time from ~/.cin_agent. To keep
tests hermetic, each test redirects memory.DATA_DIR and memory.MEMORY_FILE to a
pytest tmp_path before touching the public API. No real home directory is read
or written.
"""

import importlib

import memory


def _isolate(tmp_path, monkeypatch):
    data_dir = tmp_path / "cin_agent"
    monkeypatch.setattr(memory, "DATA_DIR", data_dir)
    monkeypatch.setattr(memory, "MEMORY_FILE", data_dir / "memory.json")


def test_remember_and_recall(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    memory.remember(42, "name", "Ada")
    assert memory.recall(42, "name") == "Ada"


def test_recall_default_when_missing(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert memory.recall(99, "nope", default="fallback") == "fallback"


def test_user_id_int_and_str_are_same_key(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    memory.remember(7, "color", "green")
    assert memory.recall("7", "color") == "green"


def test_history_append_and_get(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    memory.add_history(1, "user", "hi")
    memory.add_history(1, "assistant", "hello")
    hist = memory.get_history(1, n=10)
    assert hist == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_history_strips_timestamps(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    memory.add_history(1, "user", "hi")
    hist = memory.get_history(1)
    assert "ts" not in hist[0]


def test_history_trimmed_to_max(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(memory, "MAX_HISTORY", 5)
    for i in range(10):
        memory.add_history(1, "user", f"msg{i}")
    profile = memory.get_user_profile(1)
    assert len(profile["history"]) == 5
    # newest retained
    assert profile["history"][-1]["content"] == "msg9"


def test_get_history_n_limit(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    for i in range(6):
        memory.add_history(2, "user", f"m{i}")
    assert len(memory.get_history(2, n=3)) == 3


def test_globals_roundtrip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    memory.set_global("mode", "phosphor")
    assert memory.get_global("mode") == "phosphor"
    assert memory.get_global("missing", default=None) is None


def test_clear_user_history(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    memory.add_history(3, "user", "hi")
    memory.clear_user_history(3)
    assert memory.get_history(3) == []
    # facts survive a history clear
    memory.remember(3, "x", 1)
    memory.clear_user_history(3)
    assert memory.recall(3, "x") == 1


def test_corrupt_file_recovers(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    memory.DATA_DIR.mkdir(parents=True, exist_ok=True)
    memory.MEMORY_FILE.write_text("{ not valid json")
    # _load should swallow the error and start fresh rather than raise
    assert memory.recall(1, "anything", default="dflt") == "dflt"


def test_module_reimport_keeps_public_api():
    # Guard against accidental removal of public functions.
    mod = importlib.import_module("memory")
    for fn in ("remember", "recall", "add_history", "get_history",
               "set_global", "get_global", "clear_user_history"):
        assert hasattr(mod, fn)
