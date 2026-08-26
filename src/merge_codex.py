"""
merge_codex.py — Write VibeMon hooks into ~/.codex/hooks.json.

v29 made this integration real. The old code wrote flat {command,timeout}
entries into ~/.codex/settings.json — a file Codex CLI does not read.
Codex discovers hooks in ~/.codex/hooks.json (or [hooks] in config.toml),
with the nested Claude-style shape and a REQUIRED "type" field:

  {"hooks": {"EventName": [{"matcher"?, "hooks": [{"type": "command",
                                                   "command": …,
                                                   "timeout": …}]}]}}

Codex rejects unknown fields, so entries stay minimal (no "name" key).

TRUST GATE (important): Codex skips new/changed non-managed hooks until
the user reviews them with `/hooks` inside codex. There is NO honest way
to auto-approve — the trusted_hash registry in config.toml is Codex's
internal format and must never be written by us. The installer therefore
says "written — trust to enable", not "configured".

Event map (codex event → vibemon event), conservative per official docs:
  SessionStart                          → session_start
  SessionEnd                            → session_end
  UserPromptSubmit                      → prompt
  Stop                                  → stop
  PostToolUse (Edit|Write|apply_patch)  → activity
  PostToolUse (Bash|shell)              → bash

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

# Seconds (Codex default is 600; SessionEnd defaults to 1 — set explicitly).
CODEX_TIMEOUT_S = 10


def _cmd(notify_prefix, event):
    return {
        "type": "command",
        "command": "%s %s codex_cli" % (notify_prefix, event),
        "timeout": CODEX_TIMEOUT_S,
    }


def _build_hooks(notify_prefix):
    return {
        "SessionStart": [
            {"hooks": [_cmd(notify_prefix, "session_start")]},
        ],
        "SessionEnd": [
            {"hooks": [_cmd(notify_prefix, "session_end")]},
        ],
        "UserPromptSubmit": [
            {"hooks": [_cmd(notify_prefix, "prompt")]},
        ],
        "Stop": [
            {"hooks": [_cmd(notify_prefix, "stop")]},
        ],
        "PostToolUse": [
            # Matchers are regexes over the tool name (docs list Edit /
            # Write / apply_patch / Bash as Codex tool names; "shell" is
            # included defensively for older builds — an unmatched
            # alternative is harmless).
            {"matcher": "Edit|Write|apply_patch", "hooks": [_cmd(notify_prefix, "activity")]},
            {"matcher": "Bash|shell", "hooks": [_cmd(notify_prefix, "bash")]},
        ],
    }


VIBEMON_HOOKS = _build_hooks(DEFAULT_NOTIFY_PREFIX)


def _is_vibemon_entry(entry):
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else h
        if "vibemon" in cmd:
            return True
    return False


def _is_legacy_vibemon_entry(entry):
    """v28 wrote FLAT entries ({command, timeout}, no nested hooks list)."""
    return isinstance(entry, dict) and "vibemon" in entry.get("command", "")


def _scrub_legacy_settings(hooks_path):
    """Remove the dead v28 vibemon entries from ~/.codex/settings.json.

    Codex never read that file, but leaving our stale hooks in it invites
    confusion (and would be picked up if Codex ever starts reading it).
    Only strips vibemon entries; never creates the file, never touches
    anything else in it, and skips silently when unparseable.
    """
    legacy_path = os.path.join(os.path.dirname(hooks_path) or ".", "settings.json")
    if os.path.abspath(legacy_path) == os.path.abspath(hooks_path):
        return  # caller pointed merge() at settings.json itself — nothing legacy
    if not os.path.exists(legacy_path):
        return
    try:
        with FileLock(legacy_path):
            with open(legacy_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            if not isinstance(settings, dict):
                return
            hooks = settings.get("hooks")
            if not isinstance(hooks, dict):
                return
            changed = False
            for event_name in list(hooks.keys()):
                entries = hooks.get(event_name)
                if not isinstance(entries, list):
                    continue
                kept = [
                    e for e in entries
                    if not (_is_legacy_vibemon_entry(e)
                            or (isinstance(e, dict) and _is_vibemon_entry(e)))
                ]
                if len(kept) != len(entries):
                    changed = True
                    if kept:
                        hooks[event_name] = kept
                    else:
                        del hooks[event_name]
            if not changed:
                return
            if not hooks:
                settings.pop("hooks", None)
            dir_path = os.path.dirname(legacy_path) or "."
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".settings.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(settings, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                os.replace(tmp_path, legacy_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
    except (json.JSONDecodeError, OSError):
        # Not ours / not parseable — leave it alone.
        return


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
                        f"  ⚠ Could not parse {hooks_path}; skipping Codex CLI hook registration.",
                        file=sys.stderr,
                    )
                    return False

        if not isinstance(config, dict):
            print(
                f"  ⚠ {hooks_path} is not a JSON object; skipping Codex CLI hook registration.",
                file=sys.stderr,
            )
            return False

        hooks = config.setdefault("hooks", {})

        # Sweep vibemon entries from EVERY event first, so renamed/removed
        # registrations don't linger across upgrades.
        for event_name in list(hooks.keys()):
            entries = hooks.get(event_name)
            if not isinstance(entries, list):
                continue
            kept = [
                e for e in entries
                if not (isinstance(e, dict)
                        and (_is_vibemon_entry(e) or _is_legacy_vibemon_entry(e)))
            ]
            if kept:
                hooks[event_name] = kept
            else:
                del hooks[event_name]

        for event_name, new_entries in hooks_def.items():
            existing = hooks.get(event_name, [])
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

    # Outside the hooks.json lock (separate file, separate sentinel).
    _scrub_legacy_settings(hooks_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: merge_codex.py <hooks_path> [notify_prefix]\n")
        sys.exit(2)
    prefix = sys.argv[2] if len(sys.argv) > 2 else None
    merge(sys.argv[1], notify_prefix=prefix)
