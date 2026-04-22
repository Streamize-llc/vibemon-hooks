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

Set when the agent ran a Bash tool call (`event = "bash"`).

| Key | Type | Notes |
|---|---|---|
| `bash.category` | enum (open) | See list below. `unknown` if no rule matched. |
| `bash.head` | string ≤ 32 chars | First whitespace-delimited token. **Not** the whole command. |
| `bash.byte_len` | int ≥ 0 | Length of the original command. The body itself is **never** sent. |

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
| `tool.name` | string | Lowercased `tool_name` (`"edit"`, `"bash"`, `"task"`, etc.). |
| `tool.is_subagent` | bool | True when `tool.name == "task"` (Claude Code's Task tool). |

---

## Forward compatibility

The server (vibemon-app `/hook` function) treats `signals` as JSONB and
stores all keys verbatim. New client signal keys do not require server
changes — they appear in `hook_events.signals` automatically.

`additionalProperties: true` in the JSON Schema reflects this.

If a server-side feature wants to consume a new signal, it queries
`signals->>'new.key'` directly. The server-side fallback extractor in
`vibemon-app/supabase/functions/hook/index.ts` is only used to backfill
signals when an outdated client (envelope `v=1`) connects.
