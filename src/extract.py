"""
extract.py — VibeMon envelope builder.

Reads a Claude Code / Gemini CLI / Cursor / Codex hook payload from a
file path given by env var VIBEMON_FILE, sanitizes all bodies, derives
behavioral signals, and prints the v2 envelope as JSON to stdout.

Privacy invariants (enforced by tests/test_privacy_canary.py):
  - No code content (Write content, Edit new_string/old_string)
  - No prompt body
  - No bash command string (only the head token + classified category)
  - No tool_response / stderr text
  - Only categories, lengths, booleans, file extensions, file paths

This module is also importable for unit tests:
  from extract import build_envelope, sanitize_payload, derive_signals
"""

import json
import os
import sys

try:
    import datetime
except Exception:
    datetime = None

# Embedded for build (notify.sh concatenates classify.py before this file).
# When imported as a module, classifier helpers come from the sibling import.
try:
    from classify import classify_bash, extract_commit_message  # type: ignore
except ImportError:
    # If running as a single concatenated script, these names are already
    # in the module's namespace — defined above by the build step.
    pass


# ─── Allowlists / forbidden keys ───────────────────────────────────────
SAFE_TOP_KEYS = {
    "tool_name", "tool", "session_id", "cwd", "timestamp", "client_version",
    "project_root", "agent", "subagent_type", "matcher", "transcript_path",
    "permission_mode", "hook_event_name", "tool_use_id", "model",
    "source", "agent_type", "command_name", "command_args", "command_source",
    "expansion_type", "notification_type", "title", "load_reason", "memory_type",
    "trigger_file_path", "parent_file_path", "globs", "config_source", "trigger",
    "is_interrupt",
}

FORBIDDEN_TOP_KEYS = {
    "prompt", "message", "user_input", "text",
    "tool_response", "response", "stderr", "stdout", "error",
}

FORBIDDEN_TI_KEYS = {
    "content", "new_string", "old_string", "new_source", "old_source",
    "command", "script",
}


# ─── Helpers ───────────────────────────────────────────────────────────
def count_nonblank_lines(s):
    """Count non-blank newline-separated lines in a string."""
    if not s:
        return 0
    return sum(1 for line in s.split(chr(10)) if line.strip())


def detect_lang_hint(body):
    """Crude language detection from first 500 chars. Returns 'ko'/'en'/'mixed'."""
    if not body:
        return ""
    sample = body[:500]
    han = sum(1 for c in sample if 0xAC00 <= ord(c) <= 0xD7AF)
    ascii_alpha = sum(1 for c in sample if c.isalpha() and ord(c) < 128)
    if han > 5 and han > ascii_alpha:
        return "ko"
    if ascii_alpha > 5:
        return "en"
    return "mixed"


def bucket_chars(n):
    """Bucket prompt char count into XS/S/M/L/XL."""
    if n < 50:
        return "XS"
    if n < 200:
        return "S"
    if n < 500:
        return "M"
    if n < 2000:
        return "L"
    return "XL"


def classify_failure(err):
    """Classify a failure error string into a kind. Returns 'other' as fallback.

    Order matters: the more specific patterns (string_mismatch's "string
    to replace not found") must be checked BEFORE the generic ones
    ("not found" → file_not_found).
    """
    if not err:
        return ""
    el = err.lower()
    if "string to replace" in el or "old_string" in el or "no matches" in el:
        return "string_mismatch"
    if "no such file" in el or "enoent" in el:
        return "file_not_found"
    if "permission" in el or "denied" in el or "eacces" in el:
        return "permission"
    if "not found" in el:
        return "file_not_found"
    if "syntax" in el or "unexpected token" in el or "parse error" in el:
        return "syntax"
    if "timeout" in el or "timed out" in el:
        return "timeout"
    if "network" in el or "econnrefused" in el or "enotfound" in el or " dns " in el:
        return "network"
    if "type" in el and ("error" in el or "mismatch" in el):
        return "type_error"
    return "other"


def file_metadata(fp):
    """Extract file.* signals from a path. Returns (ext, depth, is_test, is_config, is_doc)."""
    if not isinstance(fp, str) or not fp:
        return ("", 0, False, False, False)
    base = fp.rsplit("/", 1)[-1]
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    depth = fp.count("/")
    fl = fp.lower()
    bl = base.lower()
    is_test = (
        ".test." in fl or ".spec." in fl or "_test." in fl
        or "/test/" in fl or "/tests/" in fl or "__tests__" in fl
        or "_spec." in fl
    )
    is_config = (
        bl in ("package.json", "tsconfig.json", "dockerfile", "gemfile",
               "cargo.toml", "go.mod", "requirements.txt", "pyproject.toml")
        or bl.startswith(".env")
        or "tsconfig" in bl
        or bl.endswith(".yaml") or bl.endswith(".yml") or bl.endswith(".toml")
    )
    is_doc = ext in ("md", "mdx", "rst", "txt")
    return (ext, depth, is_test, is_config, is_doc)


# ─── Core: sanitize + derive ───────────────────────────────────────────
def sanitize_payload(payload):
    """Strip ALL bodies. Returns a dict with only allowlisted top-level
    keys plus a slimmed tool_input containing at most file_path."""
    if not isinstance(payload, dict):
        return {}
    out = {}
    for k, v in payload.items():
        if k in FORBIDDEN_TOP_KEYS:
            continue
        if k == "tool_input":
            ci = {}
            if isinstance(v, dict):
                fp = v.get("file_path")
                if isinstance(fp, str) and fp:
                    ci["file_path"] = fp
            out[k] = ci
            continue
        if k in SAFE_TOP_KEYS or k.startswith("hook_"):
            out[k] = v
    return out


def derive_signals(event, payload):
    """Derive sparse signals dict from raw payload. The payload may still
    contain bodies (this function reads them but never returns them — it
    extracts shape and discards)."""
    sig = {}
    if not isinstance(payload, dict):
        return sig

    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else None
    tn = (payload.get("tool_name") or payload.get("tool") or "").lower()

    # Lines added/removed
    la, lr = 0, 0
    if ti:
        if tn in ("write", "write_file"):
            la = count_nonblank_lines(ti.get("content"))
        elif tn in ("edit", "replace", "notebookedit"):
            nw = count_nonblank_lines(ti.get("new_string") or ti.get("new_source"))
            ol = count_nonblank_lines(ti.get("old_string") or ti.get("old_source"))
            la = max(0, nw - ol)
            lr = max(0, ol - nw)
    if la or lr:
        sig["lines.added"] = la
        sig["lines.removed"] = lr
        sig["lines.net"] = la - lr

    # File metadata
    fp = ti.get("file_path") if ti else None
    if isinstance(fp, str) and fp:
        ext, depth, is_test, is_config, is_doc = file_metadata(fp)
        if ext:
            sig["file.ext"] = ext
        sig["file.depth"] = depth
        if is_test:
            sig["file.is_test"] = True
        if is_config:
            sig["file.is_config"] = True
        if is_doc:
            sig["file.is_doc"] = True

    # Bash classification — body discarded, only category + head + length.
    # Exception: git commit messages (title only, first line, 200 char cap)
    # are captured by default. Opt out with VIBEMON_NO_COMMIT_MSG=1.
    if ti and tn in ("bash", "shell", "run_command"):
        cmd = ti.get("command") or ti.get("script") or ""
        if isinstance(cmd, str) and cmd:
            cat = classify_bash(cmd)
            head = cmd.strip().split()[0] if cmd.strip() else ""
            sig["bash.category"] = cat
            sig["bash.head"] = head[:32]
            sig["bash.byte_len"] = len(cmd)
            if cat == "git.commit" and os.environ.get("VIBEMON_NO_COMMIT_MSG", "") != "1":
                msg = extract_commit_message(cmd)
                if msg:
                    sig["commit.message"] = msg

    # Prompt shape — body discarded
    if event == "prompt":
        body = ""
        for k in ("prompt", "message", "user_input", "text"):
            v = payload.get(k)
            if isinstance(v, str) and v:
                body = v
                break
        if body:
            n = len(body)
            sig["prompt.chars"] = n
            sig["prompt.bucket"] = bucket_chars(n)
            sig["prompt.has_question"] = "?" in body
            sig["prompt.has_code_fence"] = "```" in body
            sig["prompt.line_count"] = body.count(chr(10)) + 1
            sig["prompt.lang_hint"] = detect_lang_hint(body)

    # Failure classification
    if event == "tool_failure":
        err = ""
        for k in ("error", "tool_response", "response", "message", "stderr"):
            v = payload.get(k)
            if isinstance(v, str) and v:
                err = v
                break
            if isinstance(v, dict):
                err = json.dumps(v)[:1000]
                break
        if err:
            sig["failure.kind"] = classify_failure(err)
            sig["failure.byte_len"] = len(err)

    # Tool meta
    if tn:
        sig["tool.name"] = tn
    if tn == "task":
        sig["tool.is_subagent"] = True

    return sig


def local_time_fields():
    """Return (local_hour, local_dow, local_tz) from system clock. Best-effort."""
    if datetime is None:
        return (None, None, "")
    try:
        now = datetime.datetime.now().astimezone()
        return (now.hour, now.weekday(), str(now.tzinfo) if now.tzinfo else "")
    except Exception:
        return (None, None, "")


def build_envelope(event, payload, agent, cwd, timestamp, project_root=""):
    """Assemble the v2 envelope from raw inputs. The payload here is the
    RAW Claude Code payload (with bodies). This function sanitizes and
    derives in one place."""
    payload = payload if isinstance(payload, dict) else {}

    # Compute signals from raw (we read bodies, but only emit shape)
    signals = derive_signals(event, payload)

    # Strip all bodies before persisting payload
    clean = sanitize_payload(payload)

    # Re-inject computed scalars for legacy compat (server uses these directly)
    la = signals.get("lines.added", 0)
    lr = signals.get("lines.removed", 0)
    if la or lr:
        clean["lines_added"] = la
        clean["lines_removed"] = lr

    if project_root:
        clean["project_root"] = project_root

    sid = clean.get("session_id")

    local_hour, local_dow, local_tz = local_time_fields()

    env = {
        "v": 2,
        "event": event,
        "agent": agent or "claude_code",
        "cwd": cwd or "",
        "timestamp": timestamp or "",
        "payload": clean,
        "signals": signals,
    }
    if project_root:
        env["project_root"] = project_root
    if sid:
        env["session_id"] = sid
    if local_hour is not None:
        env["local_hour"] = local_hour
    if local_dow is not None:
        env["local_dow"] = local_dow
    if local_tz:
        env["local_tz"] = local_tz

    return env


# ─── Script entry point (called by notify.sh) ──────────────────────────
def _read_stdin_json(file_path):
    try:
        with open(file_path) as f:
            raw = f.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def main():
    event = os.environ.get("VIBEMON_EVT", "unknown")
    agent = os.environ.get("VIBEMON_AGENT", "claude_code")
    cwd = os.environ.get("VIBEMON_CWD", "")
    timestamp = os.environ.get("VIBEMON_TS", "")
    project_root = os.environ.get("VIBEMON_ROOT", "")
    file_path = os.environ.get("VIBEMON_FILE", "")

    payload = _read_stdin_json(file_path) if file_path else {}
    env = build_envelope(event, payload, agent, cwd, timestamp, project_root)
    sys.stdout.write(json.dumps(env, ensure_ascii=False))


if __name__ == "__main__":
    main()
