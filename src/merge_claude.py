"""
merge_claude.py — Idempotently merge VibeMon hooks into ~/.claude/settings.json.

Uses fcntl.flock + tempfile.mkstemp + os.replace for safety against
concurrent install.sh runs from multiple sessions (multi-session
invariant — see vibemon-app/CLAUDE.md).
"""

import fcntl
import json
import os
import sys
import tempfile


VIBEMON_HOOKS = {
    "PostToolUse": [
        {
            "matcher": "Edit|Write|NotebookEdit",
            "hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh activity claude_code"}],
        },
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh bash claude_code"}],
        },
    ],
    "UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh prompt claude_code"}]},
    ],
    "Stop": [
        {"hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh stop claude_code"}]},
    ],
    "Notification": [
        {
            "matcher": "permission_prompt",
            "hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh permission claude_code"}],
        },
    ],
    "SessionStart": [
        {"hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh session_start claude_code"}]},
    ],
    "SessionEnd": [
        {"hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh session_end claude_code"}]},
    ],
    "PostToolUseFailure": [
        {
            "matcher": "Edit|Write|NotebookEdit",
            "hooks": [{"type": "command", "command": "bash ~/.vibemon/notify.sh tool_failure claude_code"}],
        },
    ],
}


def _is_vibemon_entry(entry):
    """Detect any vibemon hook by 'vibemon' substring in the command."""
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else h
        if "vibemon" in cmd:
            return True
    return False


def merge(settings_path, hooks_def=None):
    """Merge VibeMon hooks into the given settings file. Idempotent.

    Strips any existing vibemon entries before adding the current set,
    so re-running upgrades cleanly. Uses an exclusive flock and atomic
    rename to survive concurrent install runs.
    """
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS

    lock_path = settings_path + ".vibemon.lock"
    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
    lock_f = open(lock_path, "w")
    fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
    try:
        settings = {}
        if os.path.exists(settings_path):
            with open(settings_path, "r") as f:
                try:
                    settings = json.load(f)
                except json.JSONDecodeError:
                    settings = {}

        hooks = settings.setdefault("hooks", {})

        for event_name, new_entries in hooks_def.items():
            existing = hooks.get(event_name, [])
            existing = [e for e in existing if not _is_vibemon_entry(e)]
            existing.extend(new_entries)
            hooks[event_name] = existing

        settings["hooks"] = hooks

        dir_path = os.path.dirname(settings_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".settings.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, settings_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    finally:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        lock_f.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_claude.py <settings_path>\n")
        sys.exit(2)
    merge(sys.argv[1])
