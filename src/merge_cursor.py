"""
merge_cursor.py — Merge VibeMon hooks into ~/.cursor/hooks.json.

Cursor's hook config is shallower than Claude/Gemini: each event maps
directly to a list of {command, timeout} entries with no nested 'hooks' array.
"""

import json
import os
import sys


VIBEMON_HOOKS = {
    "afterFileEdit": [
        {"command": "bash ~/.vibemon/notify.sh activity cursor", "timeout": 5000},
    ],
    "afterFileCreate": [
        {"command": "bash ~/.vibemon/notify.sh activity cursor", "timeout": 5000},
    ],
}


def _is_vibemon_entry(entry):
    return "vibemon" in entry.get("command", "")


def merge(hooks_path, hooks_def=None):
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS

    os.makedirs(os.path.dirname(hooks_path) or ".", exist_ok=True)
    config = {}
    if os.path.exists(hooks_path):
        with open(hooks_path, "r") as f:
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

    with open(hooks_path, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_cursor.py <hooks_path>\n")
        sys.exit(2)
    merge(sys.argv[1])
