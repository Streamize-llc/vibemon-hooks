"""
merge_cursor.py — Merge VibeMon hooks into ~/.cursor/hooks.json.

Cursor's hook config is shallower than Claude/Gemini: each event maps
directly to a list of {command, timeout} entries with no nested 'hooks'
array, plus a top-level "version": 1.

v29 rewired the events against Cursor's real hook surface (ground truth:
a hand-wired working hooks.json + the official hooks docs). The old
config registered `afterFileCreate` — an event Cursor does not have —
and used timeout 5000, copy-pasted from Gemini's milliseconds. Cursor
timeouts are SECONDS (5000 = 83 minutes). Result: zero production
events had ever arrived through this wiring.

Event map (cursor event → vibemon event):
  sessionStart        → session_start
  sessionEnd          → session_end
  beforeSubmitPrompt  → prompt
  stop                → stop
  afterFileEdit       → activity
  afterShellExecution → bash
  postToolUseFailure  → tool_failure

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

# Seconds, not milliseconds (Cursor docs; the working hand-wired config
# on record uses 10). Keep small: hooks fire on every edit/shell run.
CURSOR_TIMEOUT_S = 10

# cursor event name → vibemon event name. This dict is the single source
# the merge builds from; tests/test_merge_events.py pins it so a ghost
# event (afterFileCreate…) can never come back.
EVENT_MAP = {
    "sessionStart": "session_start",
    "sessionEnd": "session_end",
    "beforeSubmitPrompt": "prompt",
    "stop": "stop",
    "afterFileEdit": "activity",
    "afterShellExecution": "bash",
    "postToolUseFailure": "tool_failure",
}


def _build_hooks(notify_prefix):
    return {
        cursor_event: [
            {
                "command": "%s %s cursor" % (notify_prefix, vibemon_event),
                "timeout": CURSOR_TIMEOUT_S,
            },
        ]
        for cursor_event, vibemon_event in EVENT_MAP.items()
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

        if not isinstance(config, dict):
            print(
                f"  ⚠ {hooks_path} is not a JSON object; skipping Cursor hook registration.",
                file=sys.stderr,
            )
            return False

        hooks = config.setdefault("hooks", {})

        # Sweep vibemon entries from EVERY event first — not just the ones
        # we register. This is what removes the v28 ghost (`afterFileCreate`)
        # on upgrade instead of leaving it behind forever.
        for event_name in list(hooks.keys()):
            entries = hooks.get(event_name)
            if not isinstance(entries, list):
                continue
            kept = [e for e in entries if not (isinstance(e, dict) and _is_vibemon_entry(e))]
            if kept:
                hooks[event_name] = kept
            else:
                del hooks[event_name]

        for event_name, new_entries in hooks_def.items():
            existing = hooks.get(event_name, [])
            existing.extend(new_entries)
            hooks[event_name] = existing
        config["hooks"] = hooks
        # Cursor's schema carries a top-level version; write it on fresh
        # files, preserve whatever an existing file declares.
        config.setdefault("version", 1)

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
