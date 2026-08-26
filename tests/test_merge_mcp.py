"""Unit tests for merge_mcp.py — VibeMon MCP server registration (Phase 2).

The targets (~/.claude.json, ~/.cursor/mcp.json) are NOT vibemon-owned files —
~/.claude.json in particular holds all of Claude Code's user state — so the
merge must be surgical: touch only mcpServers.vibemon, preserve everything
else, and refuse to write over a file it cannot parse.
"""
import json
import os
import sys

import merge_mcp
from merge_mcp import MCP_URL, merge


KEY = "vbm_unit_test_key_1"
KEY2 = "vbm_unit_test_key_2"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _raw(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_fresh_register_claude_shape(tmp_path):
    target = str(tmp_path / "claude.json")
    assert merge(target, KEY) is True
    entry = _read(target)["mcpServers"]["vibemon"]
    assert entry == {
        "type": "http",
        "url": MCP_URL,
        "headers": {"Authorization": "Bearer %s" % KEY},
    }


def test_cursor_kind_omits_type(tmp_path):
    """Cursor's docs define remote servers by url+headers only — no "type"."""
    target = str(tmp_path / "mcp.json")
    assert merge(target, KEY, kind="cursor") is True
    entry = _read(target)["mcpServers"]["vibemon"]
    assert "type" not in entry
    assert entry == {
        "url": MCP_URL,
        "headers": {"Authorization": "Bearer %s" % KEY},
    }


def test_idempotent_rerun_is_noop(tmp_path):
    target = str(tmp_path / "claude.json")
    assert merge(target, KEY) is True
    before = _raw(target)
    assert merge(target, KEY) is False
    assert _raw(target) == before


def test_key_rotation_updates_header(tmp_path):
    target = str(tmp_path / "claude.json")
    merge(target, KEY)
    assert merge(target, KEY2) is True
    entry = _read(target)["mcpServers"]["vibemon"]
    assert entry["headers"]["Authorization"] == "Bearer %s" % KEY2


def test_preserves_other_servers_and_unrelated_state(tmp_path):
    """~/.claude.json holds ALL of Claude Code's state — only mcpServers.vibemon may change."""
    target = str(tmp_path / "claude.json")
    seed = {
        "numStartups": 42,
        "projects": {"/Users/x/proj": {"allowedTools": ["Bash"]}},
        "mcpServers": {"meta-ads": {"type": "http", "url": "https://example.com/mcp"}},
    }
    with open(target, "w", encoding="utf-8") as f:
        json.dump(seed, f)
    assert merge(target, KEY) is True
    after = _read(target)
    assert after["numStartups"] == 42
    assert after["projects"] == seed["projects"]
    assert after["mcpServers"]["meta-ads"] == seed["mcpServers"]["meta-ads"]
    assert "vibemon" in after["mcpServers"]


def test_stale_shape_converges(tmp_path):
    """A previously-written claude-shaped entry converges to the cursor shape."""
    target = str(tmp_path / "mcp.json")
    merge(target, KEY)  # writes {"type": "http", …}
    assert merge(target, KEY, kind="cursor") is True
    assert "type" not in _read(target)["mcpServers"]["vibemon"]


def test_gemini_kind_uses_httpUrl(tmp_path):
    """Gemini CLI's streamable-HTTP transport field is `httpUrl` — its
    `url` means SSE, so writing `url` would silently register a broken
    server. Shape pinned against the Gemini CLI MCP docs."""
    target = str(tmp_path / "settings.json")
    assert merge(target, KEY, kind="gemini") is True
    entry = _read(target)["mcpServers"]["vibemon"]
    assert entry == {
        "httpUrl": MCP_URL,
        "headers": {"Authorization": "Bearer %s" % KEY},
    }
    assert "url" not in entry and "type" not in entry


def test_gemini_kind_preserves_hooks_in_same_file(tmp_path):
    """~/.gemini/settings.json also holds the hook config merge_gemini
    wrote — MCP registration must only touch mcpServers.vibemon."""
    target = str(tmp_path / "settings.json")
    seed = {"hooks": {"SessionStart": [{"hooks": [{"command": "x"}]}]}, "theme": "dark"}
    with open(target, "w", encoding="utf-8") as f:
        json.dump(seed, f)
    assert merge(target, KEY, kind="gemini") is True
    after = _read(target)
    assert after["hooks"] == seed["hooks"]
    assert after["theme"] == "dark"


def test_main_gemini_kind_arg(tmp_path, monkeypatch):
    target = str(tmp_path / "settings.json")
    monkeypatch.setattr(sys, "argv", ["merge_mcp.py", target, KEY, "gemini"])
    assert merge_mcp.main() == 0
    assert "httpUrl" in _read(target)["mcpServers"]["vibemon"]


def test_main_unknown_kind_skips(tmp_path, monkeypatch):
    target = str(tmp_path / "whatever.json")
    monkeypatch.setattr(sys, "argv", ["merge_mcp.py", target, KEY, "codex"])
    assert merge_mcp.main() == 0  # skip, not an install failure (set -e)
    assert not os.path.exists(target)


def test_corrupt_json_left_untouched(tmp_path):
    target = str(tmp_path / "claude.json")
    with open(target, "w", encoding="utf-8") as f:
        f.write("{ not json !!")
    before = _raw(target)
    assert merge(target, KEY) is False
    assert _raw(target) == before


def test_non_object_mcp_servers_skipped(tmp_path):
    target = str(tmp_path / "claude.json")
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": ["not", "a", "dict"]}, f)
    before = _raw(target)
    assert merge(target, KEY) is False
    assert _raw(target) == before


def test_lock_sentinel_uses_single_suffix(tmp_path):
    """Regression: FileLock appends .vibemon.lock itself — passing a pre-suffixed
    path produced `….vibemon.lock.vibemon.lock` and diverged from the sentinel
    convention every other merge_*.py uses."""
    target = str(tmp_path / "claude.json")
    merge(target, KEY)
    assert os.path.exists(target + ".vibemon.lock")
    assert not os.path.exists(target + ".vibemon.lock.vibemon.lock")


def test_main_rejects_foreign_key_prefix(tmp_path, monkeypatch):
    target = str(tmp_path / "claude.json")
    monkeypatch.setattr(sys, "argv", ["merge_mcp.py", target, "sk-not-vibemon"])
    assert merge_mcp.main() == 0  # skip is not an install failure (set -e)
    assert not os.path.exists(target)


def test_main_cursor_kind_arg(tmp_path, monkeypatch):
    target = str(tmp_path / "mcp.json")
    monkeypatch.setattr(sys, "argv", ["merge_mcp.py", target, KEY, "cursor"])
    assert merge_mcp.main() == 0
    assert "type" not in _read(target)["mcpServers"]["vibemon"]
