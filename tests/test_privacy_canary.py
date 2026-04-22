"""Privacy canary tests — the single most important test in this repo.

Every canary_*.json fixture seeds a unique CANARY_xxx string into the
exact place where bodies could leak (Write content, Bash command,
prompt body, etc.). After running the envelope builder, the resulting
JSON must NOT contain the canary anywhere.

A failure here means a code body, prompt, or command leaked into the
wire format — which is the #1 thing PRIVACY.md promises will not happen.
"""

import glob
import json
import os
import re

from extract import build_envelope


CANARY_RE = re.compile(r"CANARY_[A-Za-z0-9_]+")


def _list_canaries(fixtures_dir):
    return sorted(glob.glob(os.path.join(fixtures_dir, "canary_*.json")))


def pytest_generate_tests(metafunc):
    if "canary_path" in metafunc.fixturenames:
        fixtures_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "contract", "fixtures",
        )
        metafunc.parametrize("canary_path", _list_canaries(fixtures_dir))


def test_canary_never_appears_in_envelope(canary_path):
    with open(canary_path) as f:
        raw = json.load(f)

    # Verify the fixture itself contains a canary (sanity)
    raw_text = json.dumps(raw)
    canaries_in_input = set(CANARY_RE.findall(raw_text))
    assert canaries_in_input, (
        f"fixture {canary_path} has no CANARY_ token — useless for canary test"
    )

    event = raw.pop("event_type", "unknown")
    raw.pop("_meta_only_for_test", None)

    env = build_envelope(
        event=event,
        payload=raw,
        agent="claude_code",
        cwd="/tmp",
        timestamp="2026-04-22T00:00:00Z",
        project_root="user/repo",
    )

    env_text = json.dumps(env, ensure_ascii=False)
    canaries_in_output = set(CANARY_RE.findall(env_text))

    assert not canaries_in_output, (
        f"\n*** PRIVACY LEAK ***\n"
        f"Fixture: {os.path.basename(canary_path)}\n"
        f"Canaries seeded: {canaries_in_input}\n"
        f"Canaries leaked into envelope: {canaries_in_output}\n"
        f"Envelope:\n{json.dumps(env, indent=2, ensure_ascii=False)}"
    )
