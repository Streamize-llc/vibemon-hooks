"""Unit tests for extract.py — sanitize_payload, derive_signals,
build_envelope. Pure function tests, no I/O."""

from extract import (
    bucket_chars,
    classify_failure,
    count_nonblank_lines,
    derive_signals,
    detect_lang_hint,
    file_metadata,
    sanitize_payload,
    build_envelope,
    FORBIDDEN_TI_KEYS,
    FORBIDDEN_TOP_KEYS,
    SAFE_TOP_KEYS,
)
from classify import extract_commit_message


# ─── pure helpers ─────────────────────────────────────────────────────
def test_count_nonblank_lines():
    assert count_nonblank_lines("") == 0
    assert count_nonblank_lines(None) == 0
    assert count_nonblank_lines("a") == 1
    assert count_nonblank_lines("a\nb\nc") == 3
    assert count_nonblank_lines("a\n\n\nb") == 2  # blanks ignored
    assert count_nonblank_lines("   \na\n   ") == 1


def test_bucket_chars():
    assert bucket_chars(0) == "XS"
    assert bucket_chars(49) == "XS"
    assert bucket_chars(50) == "S"
    assert bucket_chars(199) == "S"
    assert bucket_chars(200) == "M"
    assert bucket_chars(499) == "M"
    assert bucket_chars(500) == "L"
    assert bucket_chars(1999) == "L"
    assert bucket_chars(2000) == "XL"
    assert bucket_chars(100000) == "XL"


def test_detect_lang_hint():
    assert detect_lang_hint("") == ""
    assert detect_lang_hint("hello world this is english text") == "en"
    assert detect_lang_hint("안녕하세요 한국어 텍스트입니다 정말로요") == "ko"
    assert detect_lang_hint("123 !@# *(") == "mixed"


def test_classify_failure():
    assert classify_failure("") == ""
    assert classify_failure("ENOENT: no such file or directory") == "file_not_found"
    assert classify_failure("Permission denied (EACCES)") == "permission"
    assert classify_failure("String to replace not found") == "string_mismatch"
    assert classify_failure("SyntaxError: unexpected token <") == "syntax"
    assert classify_failure("Operation timed out after 30s") == "timeout"
    assert classify_failure("ECONNREFUSED 127.0.0.1:5432") == "network"
    assert classify_failure("TypeError: cannot read property") == "type_error"
    assert classify_failure("something else weird happened") == "other"


def test_file_metadata():
    ext, depth, is_test, is_config, is_doc = file_metadata("/a/b/c/main.ts")
    assert ext == "ts" and depth == 4
    assert not is_test and not is_config and not is_doc

    ext, _, is_test, *_ = file_metadata("/x/__tests__/foo.test.ts")
    assert ext == "ts" and is_test

    _, _, _, is_config, _ = file_metadata("/repo/package.json")
    assert is_config

    _, _, _, is_config, _ = file_metadata("/repo/.env.local")
    assert is_config

    _, _, _, _, is_doc = file_metadata("/repo/README.md")
    assert is_doc


# ─── sanitize_payload — privacy invariants ────────────────────────────
def test_sanitize_strips_forbidden_top():
    raw = {
        "tool_name": "Bash",
        "prompt": "secret prompt body",
        "message": "secret message",
        "tool_response": "secret response",
        "error": "secret error",
        "stderr": "secret stderr",
        "session_id": "s1",
    }
    out = sanitize_payload(raw)
    for k in FORBIDDEN_TOP_KEYS:
        assert k not in out, f"{k!r} leaked into sanitized payload"
    assert out["tool_name"] == "Bash"
    assert out["session_id"] == "s1"


def test_sanitize_strips_forbidden_tool_input():
    raw = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/a/b.ts",
            "old_string": "secret_old",
            "new_string": "secret_new",
            "content": "secret_content",
            "command": "rm -rf /",
        },
    }
    out = sanitize_payload(raw)
    assert out["tool_input"] == {"file_path": "/a/b.ts"}
    for k in FORBIDDEN_TI_KEYS:
        assert k not in out["tool_input"]


def test_sanitize_drops_unknown_keys():
    raw = {"unknown_key": "leak_me", "tool_name": "Bash"}
    out = sanitize_payload(raw)
    assert "unknown_key" not in out
    assert "tool_name" in out


def test_sanitize_keeps_hook_prefixed():
    raw = {"hook_event_name": "PostToolUse", "tool_name": "Edit"}
    out = sanitize_payload(raw)
    assert out["hook_event_name"] == "PostToolUse"


def test_sanitize_handles_non_dict():
    assert sanitize_payload(None) == {}
    assert sanitize_payload([]) == {}
    assert sanitize_payload("string") == {}


# ─── derive_signals ───────────────────────────────────────────────────
def test_derive_write_lines():
    sig = derive_signals("activity", {
        "tool_name": "Write",
        "tool_input": {"file_path": "/a.ts", "content": "x\ny\nz\n"},
    })
    assert sig["lines.added"] == 3
    assert sig["lines.removed"] == 0
    assert sig["lines.net"] == 3
    assert sig["file.ext"] == "ts"


def test_derive_edit_lines():
    sig = derive_signals("activity", {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/a.ts",
            "old_string": "a\nb\nc",
            "new_string": "a\nb",
        },
    })
    assert sig["lines.added"] == 0
    assert sig["lines.removed"] == 1


def test_derive_bash():
    sig = derive_signals("bash", {
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin main"},
    })
    assert sig["bash.category"] == "git.push"
    assert sig["bash.head"] == "git"
    assert sig["bash.byte_len"] == len("git push origin main")


def test_derive_prompt_shape_no_body_leak():
    body = "What does CANARY_token_xyz do?"
    sig = derive_signals("prompt", {"prompt": body})
    assert sig["prompt.chars"] == len(body)
    assert sig["prompt.bucket"] == "XS"
    assert sig["prompt.has_question"] is True
    assert sig["prompt.has_code_fence"] is False
    # CRITICAL: no canary in any signal value
    for v in sig.values():
        assert "CANARY" not in str(v)


def test_derive_failure_classification():
    sig = derive_signals("tool_failure", {
        "tool_name": "Edit",
        "tool_input": {"file_path": "/x.ts"},
        "error": "String to replace not found in file",
    })
    assert sig["failure.kind"] == "string_mismatch"
    assert sig["failure.byte_len"] > 0


def test_derive_subagent():
    sig = derive_signals("activity", {"tool_name": "Task"})
    assert sig["tool.is_subagent"] is True


# ─── build_envelope (high-level) ──────────────────────────────────────
def test_build_envelope_shape():
    env = build_envelope(
        "activity",
        {"tool_name": "Write", "tool_input": {"file_path": "/x.ts", "content": "a\n"}, "session_id": "s1"},
        agent="claude_code",
        cwd="/tmp",
        timestamp="2026-04-22T00:00:00Z",
        project_root="user/repo",
    )
    assert env["v"] == 2
    assert env["event"] == "activity"
    assert env["agent"] == "claude_code"
    assert env["session_id"] == "s1"
    assert env["project_root"] == "user/repo"
    assert env["payload"]["tool_input"] == {"file_path": "/x.ts"}
    assert env["payload"]["lines_added"] == 1
    assert env["signals"]["file.ext"] == "ts"


# ─── extract_commit_message ───────────────────────────────────────────
def test_extract_commit_message_single():
    assert extract_commit_message("git commit -m 'feat: x'") == "feat: x"
    assert extract_commit_message('git commit -m "fix: bug"') == "fix: bug"
    assert extract_commit_message("git commit -am 'chore: bump'") == "chore: bump"
    assert extract_commit_message("git commit --message='docs: y'") == "docs: y"
    assert extract_commit_message("git commit --message 'refactor: z'") == "refactor: z"


def test_extract_commit_message_first_line_only():
    # Multi-line commits — body discarded, title only.
    cmd = 'git commit -m "feat: header\n\nBody paragraph with CANARY"'
    result = extract_commit_message(cmd)
    assert result == "feat: header"
    assert "CANARY" not in result


def test_extract_commit_message_200_cap():
    long = "feat: " + ("x" * 500)
    cmd = f"git commit -m '{long}'"
    result = extract_commit_message(cmd)
    assert len(result) == 200


def test_extract_commit_message_chain():
    # The bug this v15 change fixes — agent-issued chains must yield the
    # commit title. Previously returned "" because the first token was
    # `git add`, not `git commit`.
    chain = "git add -A && git commit -m 'feat: smoke chain' && git push"
    assert extract_commit_message(chain) == "feat: smoke chain"
    # Semicolon variant.
    assert (
        extract_commit_message("git add . ; git commit -m 'fix: y' ; git push")
        == "fix: y"
    )
    # Quoted && inside message must not be treated as a separator.
    assert (
        extract_commit_message('git commit -m "feat: a && b operator"')
        == "feat: a && b operator"
    )
    # Chain WITHOUT a commit returns "".
    assert extract_commit_message("git add . && git push") == ""


def test_extract_commit_message_empty_or_invalid():
    assert extract_commit_message("") == ""
    assert extract_commit_message(None) == ""
    assert extract_commit_message("echo hello") == ""
    assert extract_commit_message("git commit") == ""  # no -m
    assert extract_commit_message("git commit --amend") == ""  # no -m
