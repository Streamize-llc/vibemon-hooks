"""Contract for the /vibemon slash command (src/commands/vibemon.md).

The command is the only path that sends agent-written text to VibeMon (D3).
These checks pin the properties that keep it user-driven:
  - the model can never invoke it on its own (disable-model-invocation)
  - it cannot deliver to another person without a permission prompt
    (handoff_send / collaboration_respond are NOT pre-allowed)
  - no blanket shell or network tools are pre-allowed
  - the installer ownership marker is present
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
CMD = ROOT / "src" / "commands" / "vibemon.md"


def _frontmatter() -> dict[str, str]:
    text = CMD.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "frontmatter block missing"
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def test_model_cannot_invoke_it():
    assert _frontmatter().get("disable-model-invocation") == "true"


def test_delivery_tools_need_a_permission_prompt():
    allowed = [t.strip() for t in _frontmatter()["allowed-tools"].split(",")]
    for tool in ("mcp__vibemon__handoff_send", "mcp__vibemon__collaboration_respond",
                 "mcp__vibemon__rescue_request", "mcp__vibemon__team_join", "mcp__vibemon__team_invite"):
        assert tool not in allowed, tool
    assert "mcp__vibemon__handoff_prepare" in allowed
    assert "mcp__vibemon__handoff_get" in allowed


def test_no_blanket_shell_or_network():
    allowed = [t.strip() for t in _frontmatter()["allowed-tools"].split(",")]
    for tool in allowed:
        assert tool != "Bash" and not tool.startswith("Bash(*") and "curl" not in tool and "WebFetch" not in tool, tool
        if tool.startswith("Bash("):
            assert tool.startswith("Bash(git "), tool
            assert not any(w in tool for w in ("push", "commit", "reset", "checkout", "rm ")), tool


def test_owner_marker_and_entry():
    text = CMD.read_text(encoding="utf-8")
    assert "vibemon-managed" in text
    assert 'entry: "vibemon_command"' in text
    # preview-before-store and the second confirmation are spelled out
    assert "보내기 / 고치기 / 취소" in text
    assert "handoff_send" in text and "permission" in text
