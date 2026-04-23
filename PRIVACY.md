# Privacy Model

This document describes exactly what `vibemon-hooks` does — and does not —
send to the VibeMon backend. Every claim here is **enforced by tests**
in [tests/](tests/) and runs in CI on every PR.

---

## TL;DR

We send categories, lengths, and booleans. We never send code, prompts,
or shell command bodies — with **one narrow exception**: git commit
message titles (first line, 200 char cap), sent by default so your
activity feed can show what you shipped. Opt out by adding
`no_commit_msg=1` to `~/.vibemon/config`.

---

## What we send

For each agent hook event, the envelope POSTed to `/hook` contains:

| Field | Example | Why |
|---|---|---|
| `event` | `"activity"`, `"bash"`, `"prompt"` | Which hook fired. |
| `agent` | `"claude_code"` | Source agent. |
| `session_id` | `"abc-123"` | Multi-session disambiguation. |
| `cwd` | `/Users/x/proj` | Project routing. |
| `project_root` | `"streamize/vibemon"` | Stable project key (git remote owner/repo, or basename). |
| `timestamp` | UTC ISO-8601 | When the hook fired. |
| `local_hour` | `23` | Time-of-day for narrative ("nocturnal coder"). |
| `local_dow` | `2` | Day of week. |
| `signals.*` | see below | Derived behavioral signals. |

### Signal categories we derive

| Signal | Type | Example values |
|---|---|---|
| `file.ext` | string | `ts`, `py`, `sql` |
| `file.depth` | int | `4` (slash count in path) |
| `file.is_test` | bool | from filename pattern |
| `file.is_config` | bool | `package.json`, `.env`, `*.yaml` etc. |
| `lines.added` / `removed` / `net` | int | non-blank line counts |
| `bash.category` | enum | `git.commit`, `pkg.test`, `deploy`, `unknown`, etc. (see [SIGNALS.md](SIGNALS.md)) |
| `bash.head` | string | `git`, `npm` (capped to 32 chars) |
| `bash.byte_len` | int | length of original command (the **content** is never sent, except `commit.message` below) |
| `commit.message` | string | git commit message **title only** (first line, 200 char cap). Sent by default for `git commit -m …`. Opt out with `no_commit_msg=1` in `~/.vibemon/config`. Multi-line bodies are discarded. |
| `prompt.chars` | int | length only |
| `prompt.bucket` | enum | `XS`/`S`/`M`/`L`/`XL` |
| `prompt.has_question` | bool | does it contain `?` |
| `prompt.has_code_fence` | bool | does it contain ` ``` ` |
| `prompt.lang_hint` | enum | `ko`/`en`/`mixed` |
| `failure.kind` | enum | `string_mismatch`, `network`, `permission`, etc. |

**File paths are sent in the clear** — they are needed to match drops to
the right project (`project_root` heuristics aren't always available)
and to power per-project dashboards. If you don't want this, see
[Opting out](#opting-out).

---

## What we never send

- **Code content** — Write content, Edit `new_string` / `old_string`,
  NotebookEdit `new_source` / `old_source`. Stripped before envelope is
  built.
- **Prompt body** — UserPromptSubmit `prompt`, `message`, `user_input`,
  `text`. The prompt text itself never leaves your machine — only its
  length, bucket, language hint, and presence of `?` or ` ``` `.
- **Bash commands** — only the first token (`git`, `npm`) and the
  classified category (`git.commit`) are sent. The rest of the command
  is read by the classifier in memory and discarded immediately. The
  one exception is documented below.
- **Tool responses / stderr / stdout** — `tool_response`, `response`,
  `stderr`, `stdout`, `error` (only the *kind* of failure is sent,
  classified from a brief substring search in memory).
- **Branch names, PR titles, secrets in any field** — none of these
  are read by VibeMon.

### The commit message exception

For `git commit -m "…"` (and `--message=`, `-am`, etc.), the message
**title** — first line only, 200 character cap — is extracted and sent
as `signals.commit.message`. This is on by default so your VibeMon
activity feed can show what you shipped. Multi-line body lines are
always discarded at the client; only the title ever leaves your machine.

To opt out, add this line to `~/.vibemon/config`:

```
no_commit_msg=1
```

The file is created on install with the option commented out. Changes
take effect on the next hook fire — no restart needed.

---

## How this is enforced

1. **`sanitize_payload()` in `src/extract.py`** — single allowlist of
   safe top-level keys (`SAFE_TOP_KEYS`) plus `tool_input.file_path`.
   Anything else is dropped.

2. **Privacy canary tests** — `tests/test_privacy_canary.py` seeds a
   unique `CANARY_xxxx` token into Write content, Bash command, and
   prompt body fixtures. After running the envelope builder, the test
   greps the resulting JSON for any `CANARY_` substring. **A single
   match fails CI.**

3. **GitHub Actions** — `test.yml` runs the canary suite on every PR
   on Ubuntu + macOS, Python 3.10 + 3.12.

4. **Reproducible build** — `scripts/build.py --check` ensures the
   committed `dist/install.sh` is exactly what `src/` produces. No room
   for a hidden change in the binary that doesn't appear in the source
   diff.

---

## Verifying for yourself

```bash
git clone https://github.com/Streamize-llc/vibemon-hooks
cd vibemon-hooks
pip install pytest
python3 -m pytest tests/test_privacy_canary.py -v
```

You'll see one PASSED line per canary fixture. If any fail, the README
is wrong and the maintainers want to know — see
[SECURITY.md](SECURITY.md).

---

## Opting out

- **Stop sending commit message titles**: add `no_commit_msg=1` to
  `~/.vibemon/config`. See [The commit message exception](#the-commit-message-exception).
- **Stop sending file paths**: not currently configurable; would require
  hashing in the extractor. File an issue if you want this.
- **Uninstall completely**: delete `~/.vibemon/`, remove vibemon entries
  from `~/.claude/settings.json`, `~/.gemini/settings.json`,
  `~/.cursor/hooks.json`, `~/.codex/settings.json`. The merge scripts
  always strip existing vibemon entries on re-install, so nothing
  lingers if you re-install with a different setup.

---

## Out-of-scope

What happens to the envelope **after** it reaches the VibeMon backend
(the `/hook` edge function in vibemon-app, the LLM diary generator,
etc.) is governed by VibeMon's overall privacy policy, not this repo.
This repo only governs the data plane on **your machine**.
