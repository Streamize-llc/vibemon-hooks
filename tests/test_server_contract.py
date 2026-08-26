"""Client-side pins of the server's acceptance contract (v29).

The /hook edge function (vibemon-app) rejects `activity` events with
400 when `payload.tool || payload.tool_name` is falsy (hook/index.ts).
Cursor payloads carry no tool_name — v28 shipped every Cursor activity
event into that 400 for months. These tests freeze the client-side
synthesis that makes the envelopes acceptable WITHOUT touching server
code.
"""

import json
import os

from extract import build_envelope, normalize_cursor_payload


FIXTURES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "contract", "fixtures",
)


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        raw = json.load(f)
    event = raw.pop("event_type", "unknown")
    agent = raw.pop("_agent", "claude_code")
    return event, agent, raw


def _envelope(name):
    event, agent, raw = _load(name)
    return build_envelope(
        event=event, payload=raw, agent=agent,
        cwd="/Users/x/proj", timestamp="<t>", project_root="user/repo",
    )


def _passes_activity_gate(env):
    """Mirror of hook/index.ts: `const tool = actPayload.tool ||
    actPayload.tool_name; ... if (!tool || !projectIdentifier) return 400`."""
    p = env["payload"]
    tool = p.get("tool") or p.get("tool_name")
    project = p.get("project_root") or p.get("project") or p.get("cwd") or env.get("cwd")
    return bool(tool) and bool(project)


def test_cursor_activity_passes_server_400_gate():
    env = _envelope("cursor_after_file_edit.json")
    assert _passes_activity_gate(env), (
        "Cursor afterFileEdit envelope would 400 at the server — "
        "tool_name synthesis broken"
    )


def test_claude_activity_still_passes_server_400_gate():
    env = _envelope("activity_edit.json")
    assert _passes_activity_gate(env)


def test_gemini_activity_still_passes_server_400_gate():
    env = _envelope("gemini_activity_tool_args.json")
    assert _passes_activity_gate(env)


def test_cursor_session_id_is_conversation_id_across_events():
    """All events of one Cursor conversation must share ONE session_id
    (multi-session invariant #2 — a missing/mismatched id makes one
    session's idle flip the UI for all)."""
    ids = set()
    for name in (
        "cursor_after_file_edit.json",
        "cursor_after_shell_git_commit.json",
        "cursor_before_submit_prompt.json",
        "cursor_stop.json",
    ):
        env = _envelope(name)
        assert env.get("session_id"), f"{name}: envelope lost its session_id"
        ids.add(env["session_id"])
    assert ids == {"conv-cursor-1"}


def test_cursor_shell_body_never_in_payload_but_classified():
    env = _envelope("cursor_after_shell_git_commit.json")
    text = json.dumps(env, ensure_ascii=False)
    assert "git commit -m" not in text  # command body must not ship
    assert env["signals"]["bash.category"] == "git.commit"
    assert env["signals"]["bash.head"] == "git"


# ─── normalize_cursor_payload unit behavior ──────────────────────────

def test_normalize_does_not_mutate_input():
    raw = {"hook_event_name": "afterFileEdit", "conversation_id": "c1",
           "file_path": "/a/b.ts"}
    snapshot = json.loads(json.dumps(raw))
    normalize_cursor_payload(raw)
    assert raw == snapshot


def test_normalize_keeps_existing_tool_name():
    p = normalize_cursor_payload({
        "hook_event_name": "postToolUseFailure",
        "tool_name": "Shell",
        "conversation_id": "c1",
    })
    assert p["tool_name"] == "Shell"


def test_normalize_without_conversation_id_keeps_session_id():
    p = normalize_cursor_payload({
        "hook_event_name": "sessionStart",
        "session_id": "s-native",
    })
    assert p["session_id"] == "s-native"


def test_normalize_non_cursor_shape_is_passthrough():
    claude_like = {"tool_name": "Edit", "tool_input": {"file_path": "/x.ts"}}
    assert normalize_cursor_payload(claude_like) == claude_like
