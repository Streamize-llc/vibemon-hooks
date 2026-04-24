"""
merge_claude.py — Idempotently merge VibeMon hooks into ~/.claude/settings.json.

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
# When imported as a module (tests, install.py), src/ is on sys.path.
try:
    from lock import FileLock
except ImportError:
    pass


# Default notify command — preserved verbatim from pre-Windows-port
# behavior. install.sh runs merge_claude.py without arguments and gets
# the bash invocation; install.py (Windows) passes notify_prefix to
# substitute the Python invocation.
DEFAULT_NOTIFY_PREFIX = "bash ~/.vibemon/notify.sh"


def _build_hooks(notify_prefix):
    """Construct the VIBEMON_HOOKS dict for a given notify command prefix."""
    return {
        "PostToolUse": [
            {
                "matcher": "Edit|Write|NotebookEdit",
                "hooks": [{"type": "command", "command": "%s activity claude_code" % notify_prefix}],
            },
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": "%s bash claude_code" % notify_prefix}],
            },
        ],
        "UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": "%s prompt claude_code" % notify_prefix}]},
        ],
        "Stop": [
            {"hooks": [{"type": "command", "command": "%s stop claude_code" % notify_prefix}]},
        ],
        "Notification": [
            {
                "matcher": "permission_prompt",
                "hooks": [{"type": "command", "command": "%s permission claude_code" % notify_prefix}],
            },
        ],
        "SessionStart": [
            {"hooks": [{"type": "command", "command": "%s session_start claude_code" % notify_prefix}]},
        ],
        "SessionEnd": [
            {"hooks": [{"type": "command", "command": "%s session_end claude_code" % notify_prefix}]},
        ],
        "PostToolUseFailure": [
            {
                "matcher": "Edit|Write|NotebookEdit",
                "hooks": [{"type": "command", "command": "%s tool_failure claude_code" % notify_prefix}],
            },
        ],
    }


VIBEMON_HOOKS = _build_hooks(DEFAULT_NOTIFY_PREFIX)


def _is_vibemon_entry(entry):
    """Detect any vibemon hook by 'vibemon' substring in the command.

    Substring match catches both the bash form (bash ~/.vibemon/notify.sh)
    and the Python form ("py" "...\\.vibemon\\notify.py"), so re-installs
    cleanly replace entries from either runtime.
    """
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else h
        if "vibemon" in cmd:
            return True
    return False


def merge(settings_path, notify_prefix=None, hooks_def=None):
    """Merge VibeMon hooks into the given settings file. Idempotent.

    notify_prefix overrides the default bash command (used by Windows
    installer where bash is not present).
    """
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
        sys.stderr.write("usage: merge_claude.py <settings_path> [notify_prefix]\n")
        sys.exit(2)
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    merge(sys.argv[1], notify_prefix=prefix)
