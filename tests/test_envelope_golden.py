"""Golden envelope tests — every fixture must produce a known-good envelope.

If you intentionally change envelope shape, run:
    python3 scripts/regen_golden.py
and review the diff before committing.
"""

import json
import os

import pytest

from extract import build_envelope


NONDETERMINISTIC = {"local_hour", "local_dow", "local_tz", "timestamp"}


def _normalize(env):
    return {k: v for k, v in env.items() if k not in NONDETERMINISTIC}


def _list_fixture_names(fixtures_dir):
    names = sorted(
        f for f in os.listdir(fixtures_dir)
        if f.endswith(".json") and not f.startswith("canary_")
    )
    return names


def pytest_generate_tests(metafunc):
    if "fixture_name" in metafunc.fixturenames:
        fixtures_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "contract", "fixtures",
        )
        metafunc.parametrize("fixture_name", _list_fixture_names(fixtures_dir))


def test_envelope_matches_golden(fixture_name, fixtures_dir, golden_dir):
    fixture_path = os.path.join(fixtures_dir, fixture_name)
    golden_path = os.path.join(golden_dir, fixture_name)

    if not os.path.exists(golden_path):
        pytest.fail(
            f"golden missing for {fixture_name}. "
            f"Run `python3 scripts/regen_golden.py` to generate."
        )

    with open(fixture_path, encoding="utf-8") as f:
        raw = json.load(f)
    event = raw.pop("event_type", "unknown")
    raw.pop("_meta_only_for_test", None)

    actual = _normalize(build_envelope(
        event=event,
        payload=raw,
        agent="claude_code",
        cwd="/Users/x/proj",
        timestamp="<redacted>",
        project_root="user/repo",
    ))

    with open(golden_path, encoding="utf-8") as f:
        expected = json.load(f)

    # Sort by serializing → loading so dict order doesn't matter
    actual_sorted = json.loads(json.dumps(actual, sort_keys=True))
    expected_sorted = json.loads(json.dumps(expected, sort_keys=True))

    assert actual_sorted == expected_sorted, (
        f"\nGolden mismatch for {fixture_name}.\n"
        f"Expected:\n{json.dumps(expected_sorted, indent=2)}\n"
        f"Actual:\n{json.dumps(actual_sorted, indent=2)}\n\n"
        f"If this change is intentional, run `python3 scripts/regen_golden.py`."
    )
