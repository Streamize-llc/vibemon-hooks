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


# ─── HEREDOC — Claude Code / agent command-substitution patterns ─────
# Discovered from production data (2026-04-23/24): 6/8 git.commit events
# had `commit.message` = "$(cat <<'EOF'" instead of the real title, because
# `shlex` tokenised the entire `"$(cat <<'EOF' ... EOF\n)"` arg as one blob
# and the old code did `.split("\n", 1)[0]` on it.

def _claude_code_style_heredoc(title, *body_lines):
    """Reproduce the exact shape Claude Code emits. See the `git commit`
    block in the project's commit protocol — HEREDOC pattern is the default."""
    body = "\n".join((title,) + body_lines)
    return (
        f'git commit -m "$(cat <<\'EOF\'\n'
        f'{body}\n'
        f'EOF\n'
        f'   )"'
    )


def test_extract_commit_message_heredoc_simple():
    cmd = _claude_code_style_heredoc("feat: v15 chain smoke test")
    assert extract_commit_message(cmd) == "feat: v15 chain smoke test"


def test_extract_commit_message_heredoc_with_body():
    cmd = _claude_code_style_heredoc(
        "feat: smoke test commit tape collection v14",
        "",
        "Body paragraph 1.",
        "Body paragraph 2.",
        "",
        "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>",
    )
    result = extract_commit_message(cmd)
    assert result == "feat: smoke test commit tape collection v14"
    # Body and footer must NOT leak through.
    assert "Body paragraph" not in result
    assert "Co-Authored-By" not in result


def test_extract_commit_message_heredoc_leading_blank():
    # Some agents/templates emit a blank line before the real title.
    cmd = (
        'git commit -m "$(cat <<\'EOF\'\n'
        "\n"
        "fix: header after blank\n"
        "\n"
        "body\n"
        'EOF\n)"'
    )
    assert extract_commit_message(cmd) == "fix: header after blank"


def test_extract_commit_message_heredoc_indented_closing():
    # `<<-EOF` variant that allows tab-indented closing delimiter.
    cmd = (
        'git commit -m "$(cat <<-EOF\n'
        "\tfeat: indented heredoc\n"
        "\tEOF\n"
        ')"'
    )
    assert extract_commit_message(cmd) == "feat: indented heredoc"


def test_extract_commit_message_heredoc_double_quoted_delim():
    # `<<"EOF"` — allowed by POSIX, occasionally emitted.
    cmd = (
        'git commit -m "$(cat <<"EOF"\n'
        "chore: double-quoted delim\n"
        'EOF\n)"'
    )
    assert extract_commit_message(cmd) == "chore: double-quoted delim"


def test_extract_commit_message_heredoc_custom_delim():
    # Delimiter doesn't have to be EOF.
    cmd = (
        'git commit -m "$(cat <<\'COMMIT_MSG\'\n'
        "docs: custom heredoc delim\n"
        "\n"
        "body\n"
        'COMMIT_MSG\n)"'
    )
    assert extract_commit_message(cmd) == "docs: custom heredoc delim"


def test_extract_commit_message_heredoc_in_chain():
    # Real-world composition: stage → heredoc commit → push.
    cmd = (
        'git add -A && git commit -m "$(cat <<\'EOF\'\n'
        "feat: chained heredoc\n"
        "\n"
        "Body here.\n"
        'EOF\n)" && git push origin main'
    )
    assert extract_commit_message(cmd) == "feat: chained heredoc"


def test_extract_commit_message_heredoc_never_leaks_body():
    cmd = _claude_code_style_heredoc(
        "chore: canary test",
        "",
        "CANARY_body_secret_xyz",
        "Co-Authored-By: evil <x@example.com>",
    )
    result = extract_commit_message(cmd)
    assert result == "chore: canary test"
    assert "CANARY" not in result
    assert "evil" not in result


def test_extract_commit_message_heredoc_never_returns_literal_pattern():
    # The bug we're fixing — make sure we never return "$(cat <<'EOF'" again.
    cmd = _claude_code_style_heredoc("feat: real title")
    result = extract_commit_message(cmd)
    assert "$(cat" not in result
    assert "<<" not in result
    assert "EOF" not in result


def test_extract_commit_message_heredoc_200_cap_on_title():
    long_title = "feat: " + ("x" * 500)
    cmd = _claude_code_style_heredoc(long_title, "", "body")
    assert len(extract_commit_message(cmd)) == 200


def test_extract_commit_message_heredoc_in_long_message_flag():
    # --message= variant with heredoc (rare but shlex-valid).
    cmd = (
        'git commit --message="$(cat <<\'EOF\'\n'
        "refactor: long-form flag heredoc\n"
        'EOF\n)"'
    )
    assert extract_commit_message(cmd) == "refactor: long-form flag heredoc"


# ─── safe_command_head — env-var / secret stripping ──────────────────
# Discovered from production data (2026-04-24): a one-off curl debugging
# session leaked the first 32 chars of `SRK='sb_secret_...'` into
# `signals.bash.head`, because the old code did `cmd.split()[0]`.

def test_safe_head_plain_command():
    from classify import safe_command_head

    assert safe_command_head("ls -la") == "ls"
    assert safe_command_head("git commit -m 'x'") == "git"
    assert safe_command_head("python script.py") == "python"


def test_safe_head_skips_env_var_prefix():
    from classify import safe_command_head

    assert safe_command_head("API_KEY=xxx curl example.com") == "curl"
    assert safe_command_head("FOO=a BAR=b baz --flag") == "baz"
    # With quoted values.
    assert safe_command_head("SRK='sb_secret_xxx' psql -c 'SELECT 1'") == "psql"
    assert safe_command_head('TOKEN="abc def" curl -H x y') == "curl"


def test_safe_head_all_env_no_command():
    from classify import safe_command_head

    # Assignment-only lines used as env sourcing in shells — no command to
    # classify, so we deliberately return a placeholder instead of leaking.
    assert safe_command_head("SRK='sb_secret_xxx'") == "<env>"
    assert safe_command_head("A=1 B=2 C=3") == "<env>"


def test_safe_head_never_leaks_env_value():
    from classify import safe_command_head

    # Reproduces the shape of a real production leak (actual value redacted).
    # The point: if a user inlines a secret-looking env-var prefix, none of
    # that value may make it into `bash.head`.
    leaky = "SRK='sb_secret_REDACTED_placeholder_for_test_xxxx' curl https://host"
    head = safe_command_head(leaky)
    assert "sb_secret" not in head
    assert "REDACTED" not in head
    assert head == "curl"


def test_safe_head_ignores_flag_shaped_tokens():
    from classify import safe_command_head

    # `--foo=bar` / `-x=y` are not env assignments (start with dash).
    assert safe_command_head("--flag=value cmd") == "--flag=value"[:32]
    assert safe_command_head("-D KEY=val script") == "-D"


def test_safe_head_empty_and_bad_input():
    from classify import safe_command_head

    assert safe_command_head("") == ""
    assert safe_command_head("   ") == ""
    assert safe_command_head(None) == ""
    # Unclosed quote — fallback path must still strip env.
    assert safe_command_head("API=\"unterminated curl host") == "curl"


def test_safe_head_32_char_cap():
    from classify import safe_command_head

    long_cmd_name = "a" * 100
    head = safe_command_head(long_cmd_name)
    assert len(head) == 32
    assert head == "a" * 32


# ─── derive_signals integration — heredoc + env prefix together ──────
def test_derive_signals_heredoc_and_env_prefix_end_to_end():
    """Regression lock: an agent running a chained command with an env-var
    prefix and a HEREDOC commit must yield `bash.head` = real command head
    AND `commit.message` = real title. Mirrors the production incident."""
    heredoc_cmd = (
        "GIT_COMMITTER_DATE='2026-04-24' "
        'git commit -m "$(cat <<\'EOF\'\n'
        "feat: integration check\n"
        "\n"
        "Long body that should be stripped.\n"
        "\n"
        "Co-Authored-By: Claude <x@example.com>\n"
        'EOF\n)"'
    )
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": heredoc_cmd},
    }
    sig = derive_signals("activity", payload)
    assert sig["bash.category"] == "git.commit"
    assert sig["bash.head"] == "git"  # not GIT_COMMITTER_DATE=... and not <env>
    assert sig["commit.message"] == "feat: integration check"
    assert "CANARY" not in (sig["commit.message"] or "")
    assert "Co-Authored-By" not in (sig["commit.message"] or "")


def test_derive_signals_env_only_bash_returns_env_placeholder():
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "SRK='sb_secret_xxx'"},
    }
    sig = derive_signals("activity", payload)
    assert sig["bash.head"] == "<env>"
    assert "sb_secret" not in sig["bash.head"]


def test_derive_signals_opt_out_blocks_heredoc_commit_message(monkeypatch):
    monkeypatch.setenv("VIBEMON_NO_COMMIT_MSG", "1")
    heredoc_cmd = (
        'git commit -m "$(cat <<\'EOF\'\n'
        "feat: should not be stored\n"
        'EOF\n)"'
    )
    payload = {"tool_name": "Bash", "tool_input": {"command": heredoc_cmd}}
    sig = derive_signals("activity", payload)
    assert sig["bash.category"] == "git.commit"
    assert "commit.message" not in sig
