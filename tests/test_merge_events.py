"""Event-wiring goldens for all four merge_*.py modules (v29).

The v28 audit found the collection layer did not match the advertising:
merge_cursor registered `afterFileCreate` (an event Cursor does not
have) with an 83-minute timeout, and merge_codex wrote a file Codex
never reads. These tests pin the FULL set of registered event names,
their vibemon event/agent arguments, and the config shapes — so a ghost
event or a wrong-file regression cannot slip back in.
"""

import json
import os
import tempfile

import merge_claude
import merge_codex
import merge_cursor
import merge_gemini


# ─── Registered event names (golden) ─────────────────────────────────

def test_claude_event_names_golden():
    assert set(merge_claude.VIBEMON_HOOKS) == {
        "PostToolUse",
        "UserPromptSubmit",
        "Stop",
        "Notification",
        "SessionStart",
        "SessionEnd",
        "PostToolUseFailure",
    }


def test_gemini_event_names_golden():
    assert set(merge_gemini.VIBEMON_HOOKS) == {
        "AfterTool",
        "SessionStart",
        "SessionEnd",
        "BeforeAgent",
        "AfterAgent",
    }


def test_cursor_event_names_golden():
    """Every name must be a real Cursor hook event (camelCase). The v28
    ghost `afterFileCreate` does not exist in Cursor and must never
    return."""
    assert set(merge_cursor.VIBEMON_HOOKS) == {
        "sessionStart",
        "sessionEnd",
        "beforeSubmitPrompt",
        "stop",
        "afterFileEdit",
        "afterShellExecution",
        "postToolUseFailure",
    }
    assert "afterFileCreate" not in merge_cursor.VIBEMON_HOOKS


def test_codex_event_names_golden():
    """Conservative set per Codex hooks docs (PascalCase)."""
    assert set(merge_codex.VIBEMON_HOOKS) == {
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
        "Stop",
        "PostToolUse",
    }


# ─── Cursor: vibemon event mapping + flat shape + seconds timeout ────

def test_cursor_event_mapping_golden():
    assert merge_cursor.EVENT_MAP == {
        "sessionStart": "session_start",
        "sessionEnd": "session_end",
        "beforeSubmitPrompt": "prompt",
        "stop": "stop",
        "afterFileEdit": "activity",
        "afterShellExecution": "bash",
        "postToolUseFailure": "tool_failure",
    }


def test_cursor_entries_flat_with_seconds_timeout():
    """Cursor timeouts are SECONDS — v28's 5000 (copied from Gemini's ms)
    meant 83 minutes. Anything above 60 is almost certainly a relapse."""
    for cursor_event, entries in merge_cursor.VIBEMON_HOOKS.items():
        for entry in entries:
            assert set(entry) == {"command", "timeout"}, (
                f"{cursor_event}: Cursor entries are flat command+timeout, got {entry}"
            )
            assert 1 <= entry["timeout"] <= 60, (
                f"{cursor_event}: timeout {entry['timeout']} does not look like seconds"
            )
            vibemon_event = merge_cursor.EVENT_MAP[cursor_event]
            assert entry["command"].endswith(f"{vibemon_event} cursor"), (
                f"{cursor_event}: command must fire `notify <event> cursor`: {entry['command']}"
            )


def test_cursor_writes_version_key(tmp_path):
    path = str(tmp_path / "hooks.json")
    merge_cursor.merge(path)
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    assert config.get("version") == 1


def test_cursor_upgrade_removes_ghost_afterFileCreate(tmp_path):
    """A v28 hooks.json (ghost event + ms timeout) must converge on merge:
    vibemon entries swept from ALL events, user entries preserved."""
    path = str(tmp_path / "hooks.json")
    v28 = {
        "hooks": {
            "afterFileEdit": [
                {"command": "bash ~/.vibemon/notify.sh activity cursor", "timeout": 5000},
                {"command": "/Users/x/.orca/agent-hooks/cursor-hook.sh", "timeout": 10},
            ],
            "afterFileCreate": [
                {"command": "bash ~/.vibemon/notify.sh activity cursor", "timeout": 5000},
            ],
        },
        "version": 1,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(v28, f)

    merge_cursor.merge(path)
    with open(path, encoding="utf-8") as f:
        config = json.load(f)

    hooks = config["hooks"]
    # Ghost event gone entirely (its only entry was ours)
    assert "afterFileCreate" not in hooks
    # User's foreign hook preserved
    edit_cmds = [e["command"] for e in hooks["afterFileEdit"]]
    assert any("orca" in c for c in edit_cmds)
    # Our entry re-added with the corrected timeout
    ours = [e for e in hooks["afterFileEdit"] if "vibemon" in e["command"]]
    assert ours and all(e["timeout"] == merge_cursor.CURSOR_TIMEOUT_S for e in ours)


# ─── Codex: right file, nested shape, required type, legacy scrub ────

def test_codex_nested_shape_and_required_type():
    """Codex requires `type` on every inner hook and rejects unknown
    fields — entries must stay minimal ({matcher?, hooks:[{type, command,
    timeout}]})."""
    for event, entries in merge_codex.VIBEMON_HOOKS.items():
        for entry in entries:
            assert set(entry) <= {"matcher", "hooks"}, (
                f"{event}: outer entry has unexpected keys: {entry}"
            )
            for h in entry["hooks"]:
                assert set(h) == {"type", "command", "timeout"}, (
                    f"{event}: inner hook has unexpected keys: {h}"
                )
                assert h["type"] == "command"
                assert h["command"].endswith("codex_cli")
                assert 1 <= h["timeout"] <= 600


def test_codex_post_tool_use_matchers():
    matchers = [e.get("matcher") for e in merge_codex.VIBEMON_HOOKS["PostToolUse"]]
    assert "Edit|Write|apply_patch" in matchers
    assert "Bash|shell" in matchers


def test_codex_target_file_is_hooks_json():
    """Codex reads ~/.codex/hooks.json — NOT settings.json (the v28 bug:
    a file Codex never reads, so zero events ever arrived)."""
    import paths

    assert paths.codex_hooks().endswith(os.path.join(".codex", "hooks.json"))
    assert not hasattr(paths, "codex_settings"), (
        "codex_settings() must stay deleted — it pointed at a file Codex does not read"
    )


def test_codex_merge_scrubs_legacy_settings_json(tmp_path):
    """Upgrading from v28 removes our dead entries from settings.json
    while leaving user content in it untouched — and writes the real
    hooks.json next to it."""
    hooks_path = str(tmp_path / "hooks.json")
    legacy_path = str(tmp_path / "settings.json")
    legacy = {
        "some_user_setting": True,
        "hooks": {
            "SessionStart": [
                {"command": "bash ~/.vibemon/notify.sh session_start codex_cli", "timeout": 5000},
                {"command": "/usr/local/bin/user-hook.sh", "timeout": 5},
            ],
            "SessionEnd": [
                {"command": "bash ~/.vibemon/notify.sh session_end codex_cli", "timeout": 5000},
            ],
        },
    }
    with open(legacy_path, "w", encoding="utf-8") as f:
        json.dump(legacy, f)

    merge_codex.merge(hooks_path)

    with open(hooks_path, encoding="utf-8") as f:
        hooks_config = json.load(f)
    assert "SessionStart" in hooks_config["hooks"]

    with open(legacy_path, encoding="utf-8") as f:
        scrubbed = json.load(f)
    assert scrubbed["some_user_setting"] is True
    start_cmds = [e["command"] for e in scrubbed["hooks"]["SessionStart"]]
    assert start_cmds == ["/usr/local/bin/user-hook.sh"]
    assert "SessionEnd" not in scrubbed["hooks"]  # only our entry → key removed


def test_codex_scrub_never_creates_settings_json(tmp_path):
    hooks_path = str(tmp_path / "hooks.json")
    merge_codex.merge(hooks_path)
    assert not os.path.exists(str(tmp_path / "settings.json"))


def test_codex_scrub_leaves_unparseable_settings_alone(tmp_path):
    hooks_path = str(tmp_path / "hooks.json")
    legacy_path = str(tmp_path / "settings.json")
    with open(legacy_path, "w", encoding="utf-8") as f:
        f.write("{ not json")
    merge_codex.merge(hooks_path)
    with open(legacy_path, encoding="utf-8") as f:
        assert f.read() == "{ not json"
