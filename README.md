# vibemon-hooks

[![test](https://github.com/Streamize-llc/vibemon-hooks/actions/workflows/test.yml/badge.svg)](https://github.com/Streamize-llc/vibemon-hooks/actions/workflows/test.yml)
[![release](https://img.shields.io/github/v/release/Streamize-llc/vibemon-hooks?label=release)](https://github.com/Streamize-llc/vibemon-hooks/releases/latest)
[![privacy](https://img.shields.io/badge/privacy-canary--tested-2ea44f)](PRIVACY.md)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

The open, auditable client that **[VibeMon](https://vibemon.dev)** runs on your machine to watch your AI-coding sessions. It sends **categories, counts, and booleans** about what you did — `git.commit`, `file.ext=tsx`, `lines.added=12`, `prompt.bucket=M` — and **never your code, prompts, or command bodies**.

This repo is the **single source of truth for everything that touches your machine**. If you ran `curl …vibemon.dev/install.sh | bash`, the script you got is built deterministically from `src/` here. Read it, diff it, pin it.

**Jump to:** [Install](#install) · [What actually leaves your machine](#what-actually-leaves-your-machine) · [Why you can trust it](#why-you-can-trust-it) · [Verify what you ran](#verify-what-you-ran) · [MCP registration](#mcp-registration-v21) · [Develop](#local-development)

---

## Install

```bash
# macOS / Linux — latest (vibemon.dev 302-redirects to the GitHub Release artifact):
curl -fsSL https://vibemon.dev/install.sh | bash -s -- YOUR_API_KEY

# Straight from GitHub, skipping the redirect (more cautious).
# Swap `latest` for a tag (e.g. `download/v26/`) to pin + audit a specific build:
curl -fsSL https://github.com/Streamize-llc/vibemon-hooks/releases/latest/download/install.sh | bash -s -- YOUR_API_KEY
```

The installer wires hooks into the AI agents it supports — **Claude Code, Gemini CLI, Cursor, and Codex CLI** — writes your key to `~/.vibemon/api-key`, and drops `~/.vibemon/notify.sh` as the per-hook handler. It requires `bash`.

**No terminal? On Windows** there's a GUI installer — `VibeMonSetup.exe` on every [release](https://github.com/Streamize-llc/vibemon-hooks/releases/latest), or [vibemon.dev/download](https://vibemon.dev/download). It bundles an embedded CPython (nothing to install first) and runs the same `install.py` the script path uses — zero install logic of its own (`installer/windows/`).

---

## What actually leaves your machine

When an AI coding agent fires a hook, `~/.vibemon/notify.sh`:

1. Reads the agent's stdin (the tool call or prompt event).
2. **Strips every body** — code content, prompt text, command strings, stderr. None of it leaves your machine.
3. Derives **categorical signals** — `git.commit`, `file.is_test`, `lines.added=12`, `prompt.bucket=M`, `failure.kind=string_mismatch`.
4. POSTs a small JSON envelope to your VibeMon backend over HTTPS with your API key.

A real file edit — `Edit` on `Button.tsx`, +3 lines — becomes an envelope like this, simplified from the golden fixture [`activity_edit.json`](contract/golden/activity_edit.json) that the tests assert byte-for-byte:

```jsonc
{
  "v": 2,
  "event": "activity",
  "agent": "claude_code",
  "cwd": "/Users/x/proj",
  "project_root": "user/repo",
  "repo_identifier": "user/repo",
  "branch": "feature/collaboration-inbox",
  "head_sha": "0123456789abcdef...",
  "session_id": "sess-edit-1",
  "payload": { "tool_name": "Edit", "tool_input": { "file_path": ".../Button.tsx" } },
  "signals": {
    "file.ext": "tsx",        // ← the extension, not the file
    "file.depth": 6,
    "lines.added": 3,         // ← a count, not the diff
    "lines.removed": 0,
    "lines.net": 3,
    "tool.name": "edit"
  }
}
// the live wire also adds timestamp + local_hour / local_dow / local_tz (see the schema)
```

The **code you wrote is not in there** — only its shape. The full signal catalog is [SIGNALS.md](SIGNALS.md); the wire format is [`contract/envelope-v2.schema.json`](contract/envelope-v2.schema.json).

### We send vs. we never send

| ✅ Sent (categories · counts · booleans) | ❌ Never sent |
|---|---|
| `event`, `agent`, `session_id`, `cwd`, `project_root`, timestamp, local hour/day/tz | **Code content** — `Write`/`Edit`/`NotebookEdit` bodies |
| `repo_identifier`, current branch, HEAD SHA | **PR titles or descriptions, secrets** in any field |
| `file.ext` · `file.depth` · `file.is_test` · `file.is_config` | **Prompt text** — only its length, bucket, language hint, `?`/```` ``` ```` presence |
| `lines.added` · `removed` · `net` (non-blank counts) | **Bash command bodies** — only the first token + a category |
| `bash.category` · `bash.head` (≤32 chars) · `bash.byte_len` | **Tool responses / stderr / stdout** — only the *kind* of failure |
| `prompt.bucket` · `prompt.has_question` · `prompt.lang_hint` | **Git remote URLs or credentials** — repo is normalized to `owner/repo` locally |
| `failure.kind` (e.g. `string_mismatch`) · `failure.byte_len` | |

**File paths and the current branch are sent in the clear** so activity, PRs,
and handoffs match the right team context. Git remote URLs are reduced locally
to `owner/repo`; no remote credential or URL is sent. There's one deliberate
exception on the "never" side ↓.

### The one exception: commit message titles

For `git commit -m "…"`, the message **title** (first line only, 200-char cap) is sent as `signals.commit.message`, on by default so your activity feed can show what you shipped. Multi-line bodies are always discarded on your machine. Opt out any time:

```bash
echo 'no_commit_msg=1' >> ~/.vibemon/config   # takes effect on the next hook, no restart
```

Full model, including every opt-out and how to uninstall completely: [PRIVACY.md](PRIVACY.md).

---

## Why you can trust it

The privacy claims above aren't prose — they're **enforced by tests that run in CI on every PR**:

- **Allowlist sanitizer** — `sanitize_payload()` in [`src/extract.py`](src/extract.py) keeps a single allowlist of safe keys (`SAFE_TOP_KEYS` + `tool_input.file_path`). Everything else is dropped before the envelope is built.
- **Privacy canary tests** — [`tests/test_privacy_canary.py`](tests/test_privacy_canary.py) seeds a unique `CANARY_xxxx` token into Write content, a Bash command, and a prompt body, builds the envelope, then greps the result. **A single `CANARY_` match fails CI.**
- **Reproducible build** — `dist/install.sh` is committed and must be byte-identical to what `src/` produces; `scripts/build.py --check` enforces it on every PR, so no change can hide in the shipped script that isn't in the source diff.
- **CI matrix** — Ubuntu + macOS, Python 3.10 + 3.12 ([`.github/workflows/test.yml`](.github/workflows/test.yml)).

Check the canary yourself in 20 seconds:

```bash
git clone https://github.com/Streamize-llc/vibemon-hooks && cd vibemon-hooks
pip install pytest && python3 -m pytest tests/test_privacy_canary.py -v
```

---

## Verify what you ran

The bytes at `vibemon.dev/install.sh` (302 → GitHub Release) must equal the committed `dist/install.sh` for that VERSION:

```bash
curl -fsSL https://vibemon.dev/install.sh > /tmp/got.sh          # what you'd run
git clone https://github.com/Streamize-llc/vibemon-hooks && cd vibemon-hooks
diff /tmp/got.sh dist/install.sh && echo "OK: byte-identical"    # what this repo ships
python3 scripts/build.py --check                                 # or rebuild from src/ and compare
```

---

## MCP registration (v21+)

Beyond hooks, the installer registers the **vibemon MCP server** (`https://vibemon.dev/api/mcp`, Streamable HTTP) so your AI agents can read and write your team TODOs with the same API key:

| File | Entry written |
|---|---|
| `~/.claude.json` (Claude Code, user scope) | `mcpServers.vibemon = {"type": "http", "url", "headers"}` |
| `~/.cursor/mcp.json` (Cursor) | `mcpServers.vibemon = {"url", "headers"}` |

The merge is **idempotent and surgical**: existing MCP servers and unrelated config are preserved; a file that can't be parsed is left untouched (registration skipped). Re-running with a rotated key updates only the `Authorization` header. Restart running agent sessions to pick it up. To remove, delete the `vibemon` entry from `mcpServers`. This adds **no new telemetry** — the privacy model above is unchanged.

---

## Repo layout

```
vibemon-hooks/
├── VERSION                        ← single source of truth (currently 26)
├── src/                           ← editable source
│   ├── install.sh / install.py    ← POSIX + Python installers (install.ps1 for Windows)
│   ├── notify.sh / notify.py      ← per-hook handler
│   ├── extract.py                 ← envelope builder + allowlist sanitizer
│   ├── classify.py                ← bash-command classifier
│   ├── merge_{claude,gemini,cursor,codex}.py   ← per-agent hook registration
│   ├── merge_mcp.py               ← MCP server registration (v21+)
│   ├── lock.py / paths.py         ← concurrency lock + path resolution
├── dist/install.{sh,ps1}          ← BUILT, COMMITTED, REPRODUCIBLE (+ .sha256)
├── contract/
│   ├── envelope-v2.schema.json    ← the wire format
│   ├── fixtures/                  ← sample agent payloads (incl. canary_* privacy probes)
│   └── golden/                    ← expected envelopes, asserted byte-for-byte
├── tests/                         ← unit · contract · privacy-canary · install-idempotency · static
├── scripts/build.py               ← src/ → dist/install.sh  (--check enforces reproducibility)
└── .github/workflows/             ← test.yml (every PR) · release.yml (on tag)
```

---

## Local development

```bash
python3 scripts/build.py                 # src/ → dist/install.sh
python3 -m pytest tests/                  # unit · contract · privacy · idempotency · static

# Add a bash classifier rule:
$EDITOR src/classify.py && $EDITOR tests/test_classify.py   # add the assertion
python3 scripts/build.py && python3 -m pytest tests/

# Change the envelope shape:
$EDITOR contract/fixtures/<event>.json
python3 scripts/regen_golden.py           # regenerate contract/golden/
git diff contract/golden/                 # REVIEW carefully — this is the wire contract
```

Adding a signal is a **contract change**: update [SIGNALS.md](SIGNALS.md), regen goldens, and note it in [CHANGELOG.md](CHANGELOG.md).

## Releasing

1. Bump `VERSION` (e.g. `26` → `27`).
2. `python3 scripts/build.py`, then commit `dist/install.sh` + `VERSION`.
3. `git tag v27 && git push --tags` → CI builds, tests, and attaches `install.sh` + `sha256sum.txt` to a GitHub Release.
4. `vibemon.dev/install.sh` redirects to the newest tag automatically.

`notify.sh` self-updates: it polls the latest release once a day on `session_start` and re-runs `install.sh` when VERSION bumps.

---

## Security & license

Report vulnerabilities privately per [SECURITY.md](SECURITY.md) — email admin@streamize.net, don't file a public issue; we respond within 72 hours.

MIT — see [LICENSE](LICENSE).
