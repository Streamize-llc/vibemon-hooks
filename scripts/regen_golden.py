#!/usr/bin/env python3
"""Regenerate contract/golden/*.json from contract/fixtures/*.json.

Run after changing fixture inputs OR signal logic. Commit the diff.
Do NOT run blindly — review the diff carefully (this is the contract
the server enforces).

Skips canary_*.json fixtures (those are tested by the privacy canary
suite, not by golden comparison).
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from extract import build_envelope  # noqa: E402

FIXTURES = os.path.join(ROOT, "contract", "fixtures")
GOLDEN = os.path.join(ROOT, "contract", "golden")

# Fields whose value depends on the system clock; redact for golden
NONDETERMINISTIC = {"local_hour", "local_dow", "local_tz", "timestamp"}


def normalize(env):
    out = {k: v for k, v in env.items() if k not in NONDETERMINISTIC}
    return out


def regen_one(fixture_path):
    with open(fixture_path, encoding="utf-8") as f:
        raw = json.load(f)
    event = raw.pop("event_type", "unknown")
    raw.pop("_meta_only_for_test", None)

    env = build_envelope(
        event=event,
        payload=raw,
        agent="claude_code",
        cwd="/Users/x/proj",
        timestamp="<redacted>",
        project_root="user/repo",
    )
    return normalize(env)


def main():
    os.makedirs(GOLDEN, exist_ok=True)
    for name in sorted(os.listdir(FIXTURES)):
        if not name.endswith(".json"):
            continue
        if name.startswith("canary_"):
            continue
        fixture = os.path.join(FIXTURES, name)
        gold = os.path.join(GOLDEN, name)
        env = regen_one(fixture)
        with open(gold, "w", encoding="utf-8", newline="\n") as f:
            json.dump(env, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        print(f"  wrote {gold}")


if __name__ == "__main__":
    main()
