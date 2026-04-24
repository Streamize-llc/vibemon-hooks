"""
merge_codex.py — Merge VibeMon session hooks into ~/.codex/settings.json.

Codex CLI only exposes session-level events.
"""

import json
import os
import sys


DEFAULT_NOTIFY_PREFIX = "bash ~/.vibemon/notify.sh"


def _build_hooks(notify_prefix):
    return {
        "SessionStart": [
            {"command": "%s session_start codex_cli" % notify_prefix, "timeout": 5000},
        ],
        "SessionEnd": [
            {"command": "%s session_end codex_cli" % notify_prefix, "timeout": 5000},
        ],
    }


VIBEMON_HOOKS = _build_hooks(DEFAULT_NOTIFY_PREFIX)


def _is_vibemon_entry(entry):
    return "vibemon" in entry.get("command", "")


def merge(settings_path, notify_prefix=None, hooks_def=None):
    if hooks_def is None:
        hooks_def = VIBEMON_HOOKS if notify_prefix is None else _build_hooks(notify_prefix)

    os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
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

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_codex.py <settings_path> [notify_prefix]\n")
        sys.exit(2)
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    merge(sys.argv[1], notify_prefix=prefix)
