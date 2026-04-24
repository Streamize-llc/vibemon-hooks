"""
merge_cursor.py — Merge VibeMon hooks into ~/.cursor/hooks.json.

Cursor's hook config is shallower than Claude/Gemini: each event maps
directly to a list of {command, timeout} entries with no nested 'hooks' array.
"""

import json
import os
import sys


DEFAULT_NOTIFY_PREFIX = "bash ~/.vibemon/notify.sh"


def _build_hooks(notify_prefix):
    return {
        "afterFileEdit": [
            {"command": "%s activity cursor" % notify_prefix, "timeout": 5000},
        ],
        "afterFileCreate": [
            {"command": "%s activity cursor" % notify_prefix, "timeout": 5000},
        ],
    }


VIBEMON_HOOKS = _build_hooks(DEFAULT_NOTIFY_PREFIX)


def _is_vibemon_entry(entry):
    return "vibemon" in entry.get("command", "")


def merge(hooks_path, notify_prefix=None, hooks_def=None):
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS if notify_prefix is None else _build_hooks(notify_prefix)

    os.makedirs(os.path.dirname(hooks_path) or ".", exist_ok=True)
    config = {}
    if os.path.exists(hooks_path):
        with open(hooks_path, "r", encoding="utf-8") as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                config = {}

    hooks = config.setdefault("hooks", {})
    for event_name, new_entries in hooks_def.items():
        existing = hooks.get(event_name, [])
        existing = [e for e in existing if not _is_vibemon_entry(e)]
        existing.extend(new_entries)
        hooks[event_name] = existing
    config["hooks"] = hooks

    with open(hooks_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_cursor.py <hooks_path> [notify_prefix]\n")
        sys.exit(2)
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    merge(sys.argv[1], notify_prefix=prefix)
