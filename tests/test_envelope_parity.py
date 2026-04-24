"""Envelope parity — notify.py (Windows path) and notify.sh (Unix path)
must produce JSON-equivalent envelopes for every fixture.

Both runtimes ultimately call extract.build_envelope() with the same
payload + meta. This test confirms notify.py wires the inputs the same
way notify.sh does, so the wire format is byte-identical and the server
sees no difference between OS install paths.

Strategy:
  - For each fixture, drive notify._fire() in-process with monkeypatched
    timestamp, project_root, vibemon_dir, and _spawn_post (capture body)
  - Compare against build_envelope() invoked the same way notify.sh does
    (via extract.main() with VIBEMON_* env vars + a temp file payload)
  - Fields that depend on system clock (local_*, timestamp) are stripped
"""

import json
import os
import subprocess
import sys
import tempfile

import pytest

import notify
from extract import build_envelope


NONDETERMINISTIC = {"local_hour", "local_dow", "local_tz", "timestamp"}


def _normalize(env):
    return {k: v for k, v in env.items() if k not in NONDETERMINISTIC}


def _fixture_event(name):
    """Derive the event type from the fixture filename."""
    if name.startswith("activity_"):
        return "activity"
    if name.startswith("bash_"):
        return "bash"
    if name.startswith("prompt_"):
        return "prompt"
    if name.startswith("session_start"):
        return "session_start"
    if name.startswith("tool_failure_"):
        return "tool_failure"
    return "unknown"


def _list_fixtures(fixtures_dir):
    return sorted(
        f for f in os.listdir(fixtures_dir)
        if f.endswith(".json") and not f.startswith("canary_")
    )


def pytest_generate_tests(metafunc):
    if "fixture_name" in metafunc.fixturenames:
        fixtures_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "contract", "fixtures",
        )
        metafunc.parametrize("fixture_name", _list_fixtures(fixtures_dir))


def _build_both(fixture_path, event, monkeypatch):
    """Run both pipelines under the SAME chdir context and return
    (notify_py_envelope, expected_envelope). Using one shared cwd
    avoids platform drift (e.g. os.chdir('/') resolves to D:\\ on
    Windows but / on POSIX)."""
    with open(fixture_path, encoding="utf-8") as f:
        raw = json.load(f)
    raw.pop("event_type", None)
    raw.pop("_meta_only_for_test", None)

    captured = {}

    def fake_spawn(body, api_key, version):
        captured["body"] = body
        captured["api_key"] = api_key
        captured["version"] = version

    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        vd = os.path.join(d, ".vibemon")
        os.makedirs(vd)
        with open(os.path.join(vd, "api-key"), "w", encoding="utf-8") as f:
            f.write("test-api-key")
        with open(os.path.join(vd, "version"), "w", encoding="utf-8") as f:
            f.write("999")

        monkeypatch.setattr(notify, "_vibemon_dir", lambda: vd)
        monkeypatch.setattr(notify, "_detect_project_root", lambda: "user/repo")
        monkeypatch.setattr(notify, "_utc_iso", lambda: "<redacted>")
        monkeypatch.setattr(notify, "_spawn_post", fake_spawn)

        try:
            os.chdir(d)
            shared_cwd = os.getcwd()  # canonical for whatever OS we're on

            # notify.py path
            rc = notify._fire(event, "claude_code", raw)
            assert rc == 0
            assert "body" in captured, "notify._fire did not invoke _spawn_post"
            notify_envelope = json.loads(captured["body"])

            # Direct build_envelope (what notify.sh's extract.main does)
            expected_envelope = build_envelope(
                event=event,
                payload=raw,
                agent="claude_code",
                cwd=shared_cwd,
                timestamp="<redacted>",
                project_root="user/repo",
            )
        finally:
            os.chdir(original_cwd)

    return notify_envelope, expected_envelope


def test_envelope_parity(fixture_name, fixtures_dir, monkeypatch):
    fixture_path = os.path.join(fixtures_dir, fixture_name)
    event = _fixture_event(fixture_name)

    notify_env, expected_env = _build_both(fixture_path, event, monkeypatch)
    actual = _normalize(notify_env)
    expected = _normalize(expected_env)

    a = json.loads(json.dumps(actual, sort_keys=True))
    e = json.loads(json.dumps(expected, sort_keys=True))
    assert a == e, (
        f"\nEnvelope parity broken for {fixture_name}.\n"
        f"notify.py emits:\n{json.dumps(a, indent=2)}\n"
        f"extract.build_envelope() emits:\n{json.dumps(e, indent=2)}"
    )


def test_envelope_parity_against_subprocess_extract(fixtures_dir, monkeypatch):
    """Cross-check: invoke extract.py as a subprocess (the way notify.sh
    does it) and confirm bytes match what notify.py captures in-process.

    Uses one fixture as a smoke test — the parametrized test above
    already covers shape parity for every fixture. This adds the
    'subprocess vs in-process' axis."""
    fixture_path = os.path.join(fixtures_dir, "activity_edit.json")
    event = "activity"

    notify_env, _ = _build_both(fixture_path, event, monkeypatch)
    py_envelope = _normalize(notify_env)

    # extract.py reads VIBEMON_CWD from env, no chdir needed. Use whatever
    # cwd python's _build_both ran under so both pipelines see the same value.
    sub_env = os.environ.copy()
    sub_env.update({
        "VIBEMON_EVT": event,
        "VIBEMON_AGENT": "claude_code",
        "VIBEMON_CWD": py_envelope.get("cwd", os.getcwd()),
        "VIBEMON_ROOT": "user/repo",
        "VIBEMON_TS": "<redacted>",
        "VIBEMON_FILE": fixture_path,
        "PYTHONIOENCODING": "utf-8",
    })
    src_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"
    )
    r = subprocess.run(
        [sys.executable, os.path.join(src_dir, "extract.py")],
        env=sub_env, capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, f"extract.py failed: {r.stderr}"
    sh_envelope = _normalize(json.loads(r.stdout))

    a = json.loads(json.dumps(sh_envelope, sort_keys=True))
    b = json.loads(json.dumps(py_envelope, sort_keys=True))
    assert a == b, (
        f"\nnotify.sh subprocess vs notify.py in-process diverged.\n"
        f"sh: {json.dumps(a, indent=2)}\n"
        f"py: {json.dumps(b, indent=2)}"
    )
