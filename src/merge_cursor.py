"""
merge_cursor.py — Merge VibeMon hooks into ~/.cursor/hooks.json.

Cursor's hook config is shallower than Claude/Gemini: each event maps
directly to a list of {command, timeout} entries with no nested 'hooks' array.

Uses an exclusive FileLock + tempfile.mkstemp + os.replace for safety
against concurrent install.sh / install.ps1 runs from multiple AI
coding sessions (multi-session invariant — see vibemon-app/CLAUDE.md).
"""

import json
import os
import sys
import tempfile

# When this file is concatenated with lock.py (via build.py's
# # %%EMBED:lock.py%% marker inside install.sh), FileLock is already
# in module scope and this import is a harmless no-op fallback.
try:
    from lock import FileLock
except ImportError:
    pass


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
    with FileLock(hooks_path):
        config = {}
        if os.path.exists(hooks_path):
            with open(hooks_path, "r", encoding="utf-8") as f:
                try:
                    config = json.load(f)
                except json.JSONDecodeError:
                    # Don't clobber a file we don't own — skip and say so.
                    print(
                        f"  ⚠ Could not parse {hooks_path}; skipping Cursor hook registration.",
                        file=sys.stderr,
                    )
                    return False

        hooks = config.setdefault("hooks", {})
        for event_name, new_entries in hooks_def.items():
            existing = hooks.get(event_name, [])
            existing = [e for e in existing if not _is_vibemon_entry(e)]
            existing.extend(new_entries)
            hooks[event_name] = existing
        config["hooks"] = hooks

        dir_path = os.path.dirname(hooks_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".hooks.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, hooks_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_cursor.py <hooks_path> [notify_prefix]\n")
        sys.exit(2)
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    merge(sys.argv[1], notify_prefix=prefix)
