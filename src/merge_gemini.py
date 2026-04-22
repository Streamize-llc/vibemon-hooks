"""
merge_gemini.py — Idempotently merge VibeMon hooks into ~/.gemini/settings.json.
"""

import fcntl
import json
import os
import sys
import tempfile


VIBEMON_HOOKS = {
    "AfterTool": [
        {
            "matcher": "write_file|replace",
            "hooks": [{
                "name": "vibemon-exp",
                "type": "command",
                "command": "bash ~/.vibemon/notify.sh activity gemini_cli",
                "timeout": 5000,
            }],
        },
    ],
    "SessionStart": [
        {"hooks": [{
            "name": "vibemon-session-start",
            "type": "command",
            "command": "bash ~/.vibemon/notify.sh session_start gemini_cli",
            "timeout": 5000,
        }]},
    ],
    "SessionEnd": [
        {"hooks": [{
            "name": "vibemon-session-end",
            "type": "command",
            "command": "bash ~/.vibemon/notify.sh session_end gemini_cli",
            "timeout": 5000,
        }]},
    ],
    "BeforeAgent": [
        {"hooks": [{
            "name": "vibemon-prompt",
            "type": "command",
            "command": "bash ~/.vibemon/notify.sh prompt gemini_cli",
            "timeout": 5000,
        }]},
    ],
    "AfterAgent": [
        {"hooks": [{
            "name": "vibemon-stop",
            "type": "command",
            "command": "bash ~/.vibemon/notify.sh stop gemini_cli",
            "timeout": 5000,
        }]},
    ],
}


def _is_vibemon_entry(entry):
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else h
        if "vibemon" in cmd:
            return True
    return False


def merge(settings_path, hooks_def=None):
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
        sys.stderr.write("usage: merge_gemini.py <settings_path>\n")
        sys.exit(2)
    merge(sys.argv[1])
