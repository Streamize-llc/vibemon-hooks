"""
install.py — VibeMon installer runner (cross-platform Python core).

Invoked by install.ps1 (Windows) after the PowerShell shim has:
  1. Verified Python 3 is on PATH
  2. Created %USERPROFILE%\\.vibemon\\
  3. Saved api-key with restricted ACL
  4. Extracted the embedded Python module bundle into ~/.vibemon/

This script then writes config, runs all merge_*.py against installed
agent settings, and fires a synchronous test probe to validate the API
key.

NOT invoked by install.sh (Unix) — that path stays on bash + notify.sh
for the D2 design (zero impact on existing Linux/macOS users).

Stdlib only.
"""

import contextlib
import io
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import paths  # noqa: E402
import notify  # noqa: E402
from merge_claude import merge as merge_claude  # noqa: E402
from merge_gemini import merge as merge_gemini  # noqa: E402
from merge_cursor import merge as merge_cursor  # noqa: E402
from merge_codex import merge as merge_codex  # noqa: E402
from merge_mcp import merge as merge_mcp  # noqa: E402


def _write_text(path, content, mode=0o644):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    try:
        os.chmod(path, mode)
    except OSError:
        # Windows ignores chmod beyond read-only; api-key ACL is set by install.ps1.
        pass


def _write_config(commit_msg_flag):
    """Replicate install.sh's _vibemon_write_config behavior:
      - "1" / "0" flag → overwrite the file with the corresponding line
      - None + no existing file → create with default (collection ON)
      - None + existing file → preserve as-is
    """
    cfg_path = os.path.join(paths.vibemon_dir(), "config")
    body_template = (
        "# VibeMon config — edit this file to change data-collection behavior.\n"
        "# Changes take effect on the next hook fire (no restart needed).\n"
        "#\n"
        "# Disable git commit message collection (titles are sent by default,\n"
        "# first line only, 200 char cap):\n"
        "%s\n"
    )
    if commit_msg_flag == "1":
        _write_text(cfg_path, body_template % "no_commit_msg=1")
        print("  ✓ Config written (commit message collection: OFF)")
    elif commit_msg_flag == "0":
        _write_text(cfg_path, body_template % "# no_commit_msg=1")
        print("  ✓ Config written (commit message collection: ON)")
    elif not os.path.exists(cfg_path):
        _write_text(cfg_path, body_template % "# no_commit_msg=1")
        print("  ✓ Config file created (%s)" % cfg_path)


def _has(executable_name, dot_dir_name):
    """Mirror install.sh's `command -v X || [ -d $HOME/.X ]` heuristic."""
    if shutil.which(executable_name):
        return True
    return os.path.isdir(os.path.join(paths.home(), dot_dir_name))


def _parse_argv(argv):
    """Positional API_KEY + version, optional --no-commit-msg /
    --collect-commit-msg / --launcher <python path>.

    --launcher pins the interpreter baked into the hook commands — the
    Windows GUI installer passes its bundled python.exe so hooks never
    depend on a system Python existing."""
    api_key = None
    version = None
    flag = None
    launcher = None
    pos = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--no-commit-msg":
            flag = "1"
        elif a == "--collect-commit-msg":
            flag = "0"
        elif a == "--launcher":
            i += 1
            launcher = argv[i] if i < len(argv) else None
        else:
            pos.append(a)
        i += 1
    if pos:
        api_key = pos[0]
    if len(pos) > 1:
        version = pos[1]
    return api_key, version, flag, launcher


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    api_key, version, commit_msg_flag, launcher = _parse_argv(argv)

    if not api_key:
        sys.stderr.write(
            "usage: install.py <API_KEY> <VERSION>"
            " [--no-commit-msg|--collect-commit-msg] [--launcher <python>]\n"
        )
        return 2

    vd = paths.vibemon_dir()
    os.makedirs(vd, exist_ok=True)

    is_update = os.path.exists(os.path.join(vd, "api-key"))

    # api-key file is normally written by the PowerShell shim with proper ACL,
    # but we also write here to support direct python install.py invocation
    # (e.g. for tests). On Windows install.ps1 has already restricted permissions.
    _write_text(os.path.join(vd, "api-key"), api_key, mode=0o600)
    print("  ✓ API key saved")

    if version:
        _write_text(os.path.join(vd, "version"), version)
        print("  ✓ Version v%s recorded" % version)

    _write_config(commit_msg_flag)

    # Compute the notify command prefix once. Quoted absolute paths so
    # spaces in user names ('C:\\Users\\Jane Doe\\...') don't break.
    notify_prefix = paths.notify_command(launcher)

    # Agent presence snapshot — taken BEFORE any merge below creates the
    # very directories these checks probe (v29: merge_claude's makedirs
    # created ~/.claude, so a post-merge check was always true and
    # Claude-less machines got MCP registrations for a missing agent).
    has_claude = _has("claude", ".claude")
    has_gemini = _has("gemini", ".gemini")
    has_cursor = _has("cursor", ".cursor")
    has_codex = _has("codex", ".codex")

    merge_claude(paths.claude_settings(), notify_prefix=notify_prefix)
    print("  ✓ Claude Code hooks configured (%s)" % paths.claude_settings())

    merge_gemini(paths.gemini_settings(), notify_prefix=notify_prefix)
    print("  ✓ Gemini CLI hooks configured (%s)" % paths.gemini_settings())

    if has_cursor:
        merge_cursor(paths.cursor_hooks(), notify_prefix=notify_prefix)
        print("  ✓ Cursor hooks configured (%s)" % paths.cursor_hooks())

    if has_codex:
        merge_codex(paths.codex_hooks(), notify_prefix=notify_prefix)
        # Honest wording: Codex skips new hooks until the user trusts them.
        print("  ✓ Codex CLI hooks written (%s)" % paths.codex_hooks())
        print("    ⚠ Codex requires approval: run `codex`, then `/hooks`, and trust")
        print("      the vibemon entries to enable them.")

    # MCP registration (Phase 2) — mirrors install.sh section 5e. Claude Code
    # gets the {"type":"http",…} user-scope shape; Cursor url+headers only;
    # Gemini httpUrl+headers. Codex is manual (TOML — see merge_mcp docstring).
    if api_key.startswith("vbm_"):
        if has_claude:
            merge_mcp(paths.claude_mcp_config(), api_key)
            print("  ✓ MCP server 'vibemon' registered (%s)" % paths.claude_mcp_config())
        if has_cursor:
            merge_mcp(paths.cursor_mcp_config(), api_key, kind="cursor")
            print("  ✓ MCP server 'vibemon' registered (%s)" % paths.cursor_mcp_config())
        if has_gemini:
            merge_mcp(paths.gemini_settings(), api_key, kind="gemini")
            print("  ✓ MCP server 'vibemon' registered (%s)" % paths.gemini_settings())

    print("")
    print("🔗 Testing connection…")
    rc = notify._fire("test", "claude_code", {})
    if rc != 0:
        return rc

    # Per-agent install probes (v29) — one script_install_status row per
    # configured agent, so the server knows WHICH agents this machine
    # wired (previously only claude_code was ever recorded). Best-effort:
    # a probe hiccup must not fail an otherwise-good install.
    probe_agents = ["gemini_cli"]
    if has_cursor:
        probe_agents.append("cursor")
    if has_codex:
        probe_agents.append("codex_cli")
    for probe_agent in probe_agents:
        try:
            # Quiet: the claude_code probe above already printed the
            # user-facing success line; these only record status rows.
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                notify._fire("test", probe_agent, {})
        except Exception:
            pass
    print("  ✓ Install probes sent (%s)" % ", ".join(["claude_code"] + probe_agents))

    print("")
    if is_update:
        print("🎉 VibeMon updated successfully!" + (" (v%s)" % version if version else ""))
    else:
        print("🎉 VibeMon installed successfully!")
        print("   Your slime will grow as you code with Claude Code, Gemini CLI, Cursor, or Codex.")
        print("")
        if commit_msg_flag == "1":
            print("   ℹ Git commit message collection: OFF (--no-commit-msg)")
            print("     Re-enable anytime: edit %s" % os.path.join(vd, "config"))
        else:
            print("   ℹ Git commit message titles (first line, 200 chars) are collected to power")
            print("     your activity feed. Opt out anytime by editing %s" % os.path.join(vd, "config"))
    print("")
    print("   ℹ MCP: restart any running Claude Code / Cursor / Gemini CLI session to")
    print("     load the 'vibemon' MCP server (verify with /mcp in Claude Code).")
    if has_codex:
        print("   ℹ Codex MCP is manual (config.toml is TOML — we won't rewrite it):")
        print("     add [mcp_servers.vibemon] to ~/.codex/config.toml if you want it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
