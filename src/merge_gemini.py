"""
merge_gemini.py — Idempotently merge VibeMon hooks into ~/.gemini/settings.json.
"""

import json
import os
import sys
import tempfile

# See merge_claude.py for the FileLock import shim explanation.
try:
    from lock import FileLock
except ImportError:
    pass


DEFAULT_NOTIFY_PREFIX = "bash ~/.vibemon/notify.sh"


def _build_hooks(notify_prefix):
    return {
        "AfterTool": [
            {
                "matcher": "write_file|replace",
                "hooks": [{
                    "name": "vibemon-exp",
                    "type": "command",
                    "command": "%s activity gemini_cli" % notify_prefix,
                    "timeout": 5000,
                }],
            },
        ],
        "SessionStart": [
            {"hooks": [{
                "name": "vibemon-session-start",
                "type": "command",
                "command": "%s session_start gemini_cli" % notify_prefix,
                "timeout": 5000,
            }]},
        ],
        "SessionEnd": [
            {"hooks": [{
                "name": "vibemon-session-end",
                "type": "command",
                "command": "%s session_end gemini_cli" % notify_prefix,
                "timeout": 5000,
            }]},
        ],
        "BeforeAgent": [
            {"hooks": [{
                "name": "vibemon-prompt",
                "type": "command",
                "command": "%s prompt gemini_cli" % notify_prefix,
                "timeout": 5000,
            }]},
        ],
        "AfterAgent": [
            {"hooks": [{
                "name": "vibemon-stop",
                "type": "command",
                "command": "%s stop gemini_cli" % notify_prefix,
                "timeout": 5000,
            }]},
        ],
    }


VIBEMON_HOOKS = _build_hooks(DEFAULT_NOTIFY_PREFIX)


def _is_vibemon_entry(entry):
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else h
        if "vibemon" in cmd:
            return True
    return False


def merge(settings_path, notify_prefix=None, hooks_def=None):
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS if notify_prefix is None else _build_hooks(notify_prefix)

    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
    with FileLock(settings_path):
        settings = {}
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
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
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, settings_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_gemini.py <settings_path> [notify_prefix]\n")
        sys.exit(2)
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    merge(sys.argv[1], notify_prefix=prefix)
