"""Add the VibeMon HTTP MCP server to a Claude / Cursor config JSON.

Both Claude Code (~/.claude.json) and Cursor (~/.cursor/mcp.json) keep a top-level
`mcpServers` object whose keys are MCP server names. We merge our entry idempotently:

  {
    "mcpServers": {
      "vibemon": {
        "type":    "http",                          # Claude Code only — see below
        "url":     "https://vibemon.dev/api/mcp",
        "headers": { "Authorization": "Bearer vbm_xxx" }
      },
      ...
    }
  }

Usage (inside install.sh): `python3 - <target.json> <api_key> [claude|cursor]`

Shape per target:
  - claude: {"type": "http", "url", "headers"} — exactly what
    `claude mcp add --transport http` writes to user scope.
  - cursor: {"url", "headers"} — Cursor's docs define remote servers by `url`
    alone (its `type` enum is for stdio), so we omit the field rather than
    feed an undocumented value to a possibly strict parser.

The script is idempotent — re-running with the same args is a no-op (apart from
updating the Authorization header when the API key rotates). The targets are
NOT vibemon-owned files (~/.claude.json holds all of Claude Code's user state),
so on any parse doubt we skip registration and leave the file untouched —
never "treat as empty and overwrite" like the hook merges do for their own
settings files.
"""

import json
import os
import sys
import tempfile

# When concatenated with lock.py (via build.py's # %%EMBED:lock.py%% marker
# inside install.sh) FileLock is already in module scope, so this import raises
# ImportError and the `pass` keeps the embedded class. When imported as a module
# (tests / install.py) src/ is on sys.path so the import succeeds. Mirrors
# merge_claude/cursor/codex: a missing lock must fail loudly (NameError), never
# silently degrade to a no-op lock that defeats the multi-session write invariant.
try:
    from lock import FileLock  # type: ignore
except ImportError:
    pass


MCP_URL = "https://vibemon.dev/api/mcp"


def merge(target_path: str, api_key: str, include_type: bool = True) -> bool:
    """Insert/update the vibemon entry. Returns True if the file changed.

    include_type=False writes the Cursor shape (url + headers, no "type").
    """
    target_dir = os.path.dirname(target_path) or "."
    os.makedirs(target_dir, exist_ok=True)

    # FileLock appends ".vibemon.lock" itself — pass the protected path,
    # same convention as the merge_{claude,gemini,cursor,codex} callers.
    with FileLock(target_path):
        # Read existing
        data = {}
        if os.path.exists(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                    data = json.loads(raw) if raw else {}
            except (json.JSONDecodeError, OSError):
                # Don't corrupt invalid JSON — surface and exit
                print(f"  ⚠ Could not parse {target_path}; skipping MCP registration.", file=sys.stderr)
                return False

        if not isinstance(data, dict):
            print(f"  ⚠ {target_path} is not a JSON object; skipping MCP registration.", file=sys.stderr)
            return False

        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            print(f"  ⚠ mcpServers in {target_path} is not an object; skipping MCP registration.", file=sys.stderr)
            return False

        existing = servers.get("vibemon")
        desired = {
            "url": MCP_URL,
            "headers": {"Authorization": f"Bearer {api_key}"},
        }
        if include_type:
            desired = {"type": "http", **desired}

        if existing == desired:
            return False  # already up to date

        servers["vibemon"] = desired

        # Atomic write — temp file in same dir then os.replace
        fd, tmp = tempfile.mkstemp(dir=target_dir, prefix=".vibemon.", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, target_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    return True


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: merge_mcp.py <target_path> <api_key> [claude|cursor]", file=sys.stderr)
        return 2
    target_path = sys.argv[1]
    api_key = sys.argv[2]
    kind = sys.argv[3] if len(sys.argv) > 3 else "claude"
    if not api_key.startswith("vbm_"):
        print("  ⚠ API key does not start with 'vbm_'; skipping MCP registration.", file=sys.stderr)
        return 0
    changed = merge(target_path, api_key, include_type=(kind != "cursor"))
    if changed:
        print(f"  ✓ MCP server 'vibemon' registered in {target_path}")
    else:
        print(f"  · MCP server already up-to-date in {target_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
