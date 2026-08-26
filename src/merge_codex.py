"""
merge_codex.py — Merge VibeMon session hooks into ~/.codex/settings.json.

Codex CLI only exposes session-level events.

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
    with FileLock(settings_path):
        settings = {}
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                try:
                    settings = json.load(f)
                except json.JSONDecodeError:
                    # Don't clobber a file we don't own — skip and say so.
                    print(
                        f"  ⚠ Could not parse {settings_path}; skipping Codex CLI hook registration.",
                        file=sys.stderr,
                    )
                    return False

        if not isinstance(settings, dict):
            print(
                f"  ⚠ {settings_path} is not a JSON object; skipping Codex CLI hook registration.",
                file=sys.stderr,
            )
            return False

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
        sys.stderr.write("usage: merge_codex.py <settings_path> [notify_prefix]\n")
        sys.exit(2)
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    merge(sys.argv[1], notify_prefix=prefix)
