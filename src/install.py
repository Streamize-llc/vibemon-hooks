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

    merge_claude(paths.claude_settings(), notify_prefix=notify_prefix)
    print("  ✓ Claude Code hooks configured (%s)" % paths.claude_settings())

    merge_gemini(paths.gemini_settings(), notify_prefix=notify_prefix)
    print("  ✓ Gemini CLI hooks configured (%s)" % paths.gemini_settings())

    if _has("cursor", ".cursor"):
        merge_cursor(paths.cursor_hooks(), notify_prefix=notify_prefix)
        print("  ✓ Cursor hooks configured (%s)" % paths.cursor_hooks())

    if _has("codex", ".codex"):
        merge_codex(paths.codex_settings(), notify_prefix=notify_prefix)
        print("  ✓ Codex CLI hooks configured (%s)" % paths.codex_settings())

    # MCP registration (Phase 2) — mirrors install.sh section 5e. Claude Code
    # gets the {"type":"http",…} user-scope shape; Cursor gets url+headers only.
    if api_key.startswith("vbm_"):
        if _has("claude", ".claude"):
            merge_mcp(paths.claude_mcp_config(), api_key)
            print("  ✓ MCP server 'vibemon' registered (%s)" % paths.claude_mcp_config())
        if _has("cursor", ".cursor"):
            merge_mcp(paths.cursor_mcp_config(), api_key, include_type=False)
            print("  ✓ MCP server 'vibemon' registered (%s)" % paths.cursor_mcp_config())

    print("")
    print("🔗 Testing connection…")
    rc = notify._fire("test", "claude_code", {})
    if rc != 0:
        return rc

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
    print("   ℹ MCP: restart any running Claude Code / Cursor session to load the")
    print("     'vibemon' MCP server (verify with /mcp in Claude Code).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
