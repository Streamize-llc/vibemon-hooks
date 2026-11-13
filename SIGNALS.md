# Signal Catalog

Every key that may appear in `envelope.signals.*`. This file plus
[contract/envelope-v2.schema.json](contract/envelope-v2.schema.json)
form the complete contract that the VibeMon backend consumes.

Adding a new signal is a contract change — bump tests, regen goldens,
note in CHANGELOG.

---

## File metadata

Set when the agent's `tool_input.file_path` is present.

| Key | Type | Source | Notes |
|---|---|---|---|
| `file.ext` | string | client | Lowercase extension (no dot). `""` if none. |
| `file.depth` | int | client | Slash count in path. 0 = bare filename. |
| `file.is_test` | bool | client | Matches `.test.`, `.spec.`, `_test.`, `/tests?/`, `__tests__`. |
| `file.is_config` | bool | client | `package.json`, `tsconfig*`, `.env*`, `*.ya?ml`, `*.toml`, `Dockerfile`, `Gemfile`, `Cargo.toml`, `go.mod`, `requirements.txt`, `pyproject.toml`. |
| `file.is_doc` | bool | client | Extension in `md`, `mdx`, `rst`, `txt`. |

## Lines

Set for `Write`, `Edit`, `NotebookEdit`. Counts are non-blank.

| Key | Type | Notes |
|---|---|---|
| `lines.added` | int ≥ 0 | |
| `lines.removed` | int ≥ 0 | |
| `lines.net` | int | added − removed (can be negative) |

## Bash

Set when the agent ran a shell tool call (`event = "bash"` — Claude Code
Bash, Gemini `run_shell_command`, Cursor `afterShellExecution`, Codex
Bash) and on `tool_failure` events whose failing tool was a shell.

| Key | Type | Notes |
|---|---|---|
| `bash.category` | enum (open) | See list below. `unknown` if no rule matched. |
| `bash.head` | string ≤ 32 chars | First **real command** token — inline env-var assignments (`KEY=VAL cmd …`) are skipped so a leading secret can never leak; a command that is *only* assignments becomes `<env>`. **Not** the whole command. |
| `bash.byte_len` | int ≥ 0 | Length of the original command. The body itself is **never** sent. |
| `commit.message` | string ≤ 200 chars | Git commit **title** (first non-empty line), only when `bash.category = git.commit`. HEREDOC `-m "$(cat <<'EOF' …)"` forms are unwrapped. On by default; opt out with `no_commit_msg=1` in `~/.vibemon/config` (env `VIBEMON_NO_COMMIT_MSG=1`). |

Bash categories:

```
git.commit, git.push, git.sync, git.read, git.rewrite, git.branch, git.other
github.pr_write, github.other
pkg.test, pkg.install, pkg.build, pkg.lint, pkg.run, pkg.other
test.run, lint.run
infra.docker, infra.k8s, infra.iac
net.request, net.transfer
fs.mutate, fs.read, fs.search, fs.create
db.client, deploy, runtime, build.sys
shell.builtin, shell.nav, pkg.system
editor, mobile.expo, mobile.build, unknown
```

The classifier rules live in [src/classify.py](src/classify.py); test
coverage in [tests/test_classify.py](tests/test_classify.py).

## Prompt

Set for `event = "prompt"`. The body itself is read in-memory, shape is
extracted, and the body is then dropped.

| Key | Type | Notes |
|---|---|---|
| `prompt.chars` | int ≥ 0 | Character count. |
| `prompt.bucket` | enum | `XS` <50, `S` 50-199, `M` 200-499, `L` 500-1999, `XL` ≥2000. |
| `prompt.has_question` | bool | Contains `?`. |
| `prompt.has_code_fence` | bool | Contains ` ``` `. |
| `prompt.line_count` | int ≥ 1 | Newline count + 1. |
| `prompt.lang_hint` | enum | `ko`/`en`/`mixed` from char-range heuristic on first 500 chars. |

## Failure

Set for `event = "tool_failure"`.

| Key | Type | Notes |
|---|---|---|
| `failure.kind` | enum | `string_mismatch`, `file_not_found`, `permission`, `syntax`, `timeout`, `network`, `type_error`, `other`. |
| `failure.byte_len` | int ≥ 0 | Length of the error string (not its content). |

Order of substring matching in [src/extract.py](src/extract.py)
`classify_failure()` matters — `string_mismatch` is checked before
`file_not_found` because `"String to replace not found"` contains both.

## Tool meta

| Key | Type | Notes |
|---|---|---|
| `tool.name` | string | Lowercased `tool_name` (`"edit"`, `"bash"`, `"task"`, etc.). For Cursor it is synthesized client-side from `hook_event_name` (`afterFileEdit` → `"edit"`, `afterShellExecution` → `"bash"`). |
| `tool.is_subagent` | bool | True when `tool.name == "task"` (Claude Code's Task tool). |
| `tool.duration_ms` | int ≥ 0 | Tool wall time. Set on `activity` / `tool_failure` when the agent reports it — Claude Code ≥ 2.1.119 (`duration_ms`), Cursor (`duration`). |
| `tool.duration_unavailable` | bool | Set (true) on `activity` / `tool_failure` when the agent reports **no** duration (Gemini CLI, Codex CLI, older Claude Code) — lets analytics mask "no data" instead of misreading it as an instant tool. Exactly one of `tool.duration_ms` / `tool.duration_unavailable` appears on those events. |

---

## Forward compatibility — server allowlist (since 2026-11-13)

The server (vibemon-app `/hook`, `supabase/functions/_shared/hookPrivacy.ts`)
stores **only the signal keys listed in this file**, each checked for type
and shape (`filterSignals`). Unknown keys are dropped silently — a new client
signal must be added to the server allowlist *before* clients start sending
it, or it never reaches `hook_events.signals`.

Server-side normalisation:
- `bash.head`: a value containing `=` (an env assignment like `TOKEN=… cmd`)
  is dropped; a path is reduced to the binary name; text after a shell
  operator (`&&`, `|`, `;`, `(`) is cut.
- `commit.message`: first non-empty line, ≤ 200 chars.

The payload is filtered the same way (`sanitizePayload`): only routing fields
(tool name, session id, cwd, project root, hook event name, permission mode,
model, agent type, durations, …) and `tool_input.file_path` are stored.
`transcript_path` and any field not on the list are discarded.

`additionalProperties: true` in the JSON Schema only means the *client* may
send more; the server keeps the allowlisted subset.

The server-side fallback extractor in `vibemon-app/supabase/functions/hook/index.ts`
still backfills signals for an outdated client (envelope `v=1`); its output
passes through the same allowlist.
