"""End-to-end test of merge_*.py scripts — settings.json merge must be
idempotent (run twice = same result) and must coexist with user hooks."""

import json
import os
import tempfile

from merge_claude import merge as merge_claude
from merge_gemini import merge as merge_gemini
from merge_cursor import merge as merge_cursor
from merge_codex import merge as merge_codex


def _read(p):
    with open(p) as f:
        return json.load(f)


def test_claude_merge_into_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "settings.json")
        merge_claude(path)
        s = _read(path)
        assert "hooks" in s
        assert "PostToolUse" in s["hooks"]
        # Bash matcher should be present (PRD requirement)
        bash_entry = [e for e in s["hooks"]["PostToolUse"] if e.get("matcher") == "Bash"]
        assert bash_entry, "Bash matcher missing from PostToolUse"


def test_claude_merge_idempotent():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "settings.json")
        merge_claude(path)
        first = _read(path)
        merge_claude(path)
        second = _read(path)
        assert first == second, "claude merge is not idempotent — entries duplicated"


def test_claude_merge_preserves_user_hooks():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "settings.json")
        # Pre-populate with a non-vibemon user hook
        user_settings = {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Edit",
                        "hooks": [{"type": "command", "command": "/usr/local/bin/my-user-hook.sh"}],
                    }
                ],
                "Stop": [
                    {"hooks": [{"type": "command", "command": "/path/to/user-stop"}]}
                ],
            }
        }
        with open(path, "w") as f:
            json.dump(user_settings, f)

        merge_claude(path)
        s = _read(path)

        # User's edit hook still present
        all_cmds = []
        for entry in s["hooks"]["PostToolUse"]:
            for h in entry["hooks"]:
                all_cmds.append(h.get("command", ""))
        assert any("my-user-hook.sh" in c for c in all_cmds)

        # Vibemon's hooks added
        assert any("vibemon" in c for c in all_cmds)

        # User's stop hook still there
        stop_cmds = [h["command"] for entry in s["hooks"]["Stop"] for h in entry["hooks"]]
        assert any("user-stop" in c for c in stop_cmds)
        assert any("vibemon" in c for c in stop_cmds)


def test_claude_merge_replaces_old_vibemon_entries():
    """Re-install upgrades cleanly — old vibemon entries replaced by new."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "settings.json")
        old_settings = {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Edit",
                        "hooks": [{"type": "command", "command": "bash ~/.vibemon/old-notify.sh"}],
                    }
                ]
            }
        }
        with open(path, "w") as f:
            json.dump(old_settings, f)

        merge_claude(path)
        s = _read(path)
        cmds = [h["command"] for entry in s["hooks"]["PostToolUse"] for h in entry["hooks"]]
        # Old vibemon entry removed
        assert not any("old-notify.sh" in c for c in cmds), \
            f"old vibemon entry not replaced: {cmds}"
        # New vibemon entries present
        assert any("vibemon/notify.sh" in c for c in cmds)


def test_gemini_merge_idempotent():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "settings.json")
        merge_gemini(path)
        first = _read(path)
        merge_gemini(path)
        assert first == _read(path)


def test_cursor_merge_idempotent():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "hooks.json")
        merge_cursor(path)
        first = _read(path)
        merge_cursor(path)
        assert first == _read(path)


def test_codex_merge_idempotent():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "settings.json")
        merge_codex(path)
        first = _read(path)
        merge_codex(path)
        assert first == _read(path)


def test_corrupt_settings_treated_as_empty():
    """If settings.json is malformed JSON, mergers should overwrite, not crash."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "settings.json")
        with open(path, "w") as f:
            f.write("{ this is not json")
        merge_claude(path)
        # Should not throw; result should be valid
        s = _read(path)
        assert "hooks" in s
