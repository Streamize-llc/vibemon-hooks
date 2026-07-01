# vibemon-hooks

[![test](https://github.com/Streamize-llc/vibemon-hooks/actions/workflows/test.yml/badge.svg)](https://github.com/Streamize-llc/vibemon-hooks/actions/workflows/test.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

The bash + Python that **VibeMon** runs on your machine to observe your
AI coding sessions. This repo is the **single source of truth** for
everything that touches your local environment.

If you ran `curl …vibemon.dev/install.sh | bash`, the script you got is
built deterministically from `src/` in this repo. Read it, audit it,
pin it.

```bash
# Install (latest — vibemon.dev redirects to the GitHub Release artifact):
curl -fsSL https://vibemon.dev/install.sh | sh -s -- YOUR_API_KEY

# Pin to a specific version (more cautious — swap v25 for any tag on the releases page):
curl -fsSL https://github.com/Streamize-llc/vibemon-hooks/releases/download/v25/install.sh | sh -s -- YOUR_API_KEY
```

No terminal? On **Windows** there's a GUI installer — `VibeMonSetup.exe`
on every release, or [vibemon.dev/download](https://vibemon.dev/download).
It bundles an embedded CPython (nothing to install first) and runs the
same `install.py` the script path uses — zero install logic of its own
(`installer/windows/`). macOS/Linux stay on the one-liner above.

> **Before you install, two things to know:**
> - **Auto-update:** on session start (once/day) VibeMon checks for a new
>   release and installs it. Updates are **Ed25519-signed and verified against a
>   key baked into the client before running** — a tampered release fails
>   verification and is not executed ([SECURITY.md](SECURITY.md)). Pin a tag (the
>   second command above) if you'd rather update by hand.
> - **Telemetry:** hooks send an anonymized activity envelope (event type,
>   file paths/extensions, line counts, git `owner/repo`, local hour/timezone).
>   **Code, prompts, diffs, and command bodies are stripped** and this is
>   enforced in CI. Full details + opt-outs: [PRIVACY.md](PRIVACY.md).

---

## What this code does

When an AI coding agent fires a hook, `~/.vibemon/notify.sh`:

1. Reads the agent's stdin (the tool call or prompt event).
2. **Strips all bodies** — code content, prompt text, command strings,
   stderr output. None of this leaves your machine.
3. Derives **categorical signals** — `git.commit`, `pkg.test`,
   `file.is_test`, `prompt.bucket=M`, `failure.kind=string_mismatch`,
   `lines.added=12`, etc.
4. POSTs the resulting JSON envelope to your VibeMon backend over HTTPS
   with your API key.

Full signal catalog: [SIGNALS.md](SIGNALS.md). Wire format:
[contract/envelope-v2.schema.json](contract/envelope-v2.schema.json).
Privacy guarantees: [PRIVACY.md](PRIVACY.md).

### MCP registration (v21+)

Besides hooks, the installer registers the **vibemon MCP server**
(`https://vibemon.dev/api/mcp`, Streamable HTTP) so your AI agents can
read and write your team TODOs with the same API key:

| File | Entry written |
|---|---|
| `~/.claude.json` (Claude Code, user scope) | `mcpServers.vibemon = {"type": "http", "url", "headers"}` |
| `~/.cursor/mcp.json` (Cursor) | `mcpServers.vibemon = {"url", "headers"}` |

The merge is idempotent and surgical: existing MCP servers and all
unrelated config are preserved; a file that can't be parsed is left
untouched (registration skipped). Re-running with a rotated key updates
only the `Authorization` header. Restart running agent sessions to pick
the server up. To remove, delete the `vibemon` entry from `mcpServers`
in those files.

---

## Repo layout

```
vibemon-hooks/
├── VERSION                              ← single source of truth (e.g. "12")
├── src/                                 ← editable source
│   ├── install.sh                       ← user-facing entry point
│   ├── notify.sh                        ← per-hook handler
│   ├── extract.py                       ← envelope builder + sanitizer
│   ├── classify.py                      ← bash command classifier
│   ├── merge_{claude,gemini,cursor,codex}.py
│   └── merge_mcp.py                     ← MCP server registration (v21+)
├── dist/install.sh                      ← BUILT, COMMITTED, REPRODUCIBLE
├── dist/install.sh.sha256               ← integrity hash
├── contract/
│   ├── envelope-v2.schema.json          ← wire format JSON Schema
│   ├── fixtures/                        ← sample agent payloads
│   └── golden/                          ← expected envelopes
├── tests/                               ← 4-layer test suite
│   ├── test_classify.py                 ← unit
│   ├── test_extract.py                  ← unit
│   ├── test_envelope_golden.py          ← contract
│   ├── test_privacy_canary.py           ← privacy invariant
│   ├── test_install_idempotent.py       ← merge safety
│   ├── test_merge_mcp.py                ← MCP registration safety
│   └── test_static.py                   ← bash -n + py_compile + heredoc exec + reproducibility
├── scripts/
│   ├── build.py                         ← src/ → dist/install.sh
│   └── regen_golden.py                  ← refresh contract goldens
└── .github/workflows/
    ├── test.yml                         ← every PR
    └── release.yml                      ← on tag push
```

---

## Verifying what you ran

The contents at `vibemon.dev/install.sh` (302 → GitHub Release artifact)
must match the committed `dist/install.sh` for that VERSION:

```bash
# 1. Download the artifact you ran
curl -fsSL https://vibemon.dev/install.sh > /tmp/got.sh

# 2. Compare to this repo
git clone https://github.com/Streamize-llc/vibemon-hooks
cd vibemon-hooks
diff /tmp/got.sh dist/install.sh && echo "OK: byte-identical"

# 3. Or rebuild from source and compare
python3 scripts/build.py --check
```

Reproducibility is enforced in CI — every PR runs `scripts/build.py
--check` to fail if `dist/install.sh` is stale.

---

## Local development

```bash
# Build
python3 scripts/build.py

# Run all tests
bash tests/run.sh
# or
python3 -m pytest tests/

# Add a new bash classifier rule
$EDITOR src/classify.py
$EDITOR tests/test_classify.py        # add an assertion
python3 scripts/build.py
python3 -m pytest tests/

# Add a new fixture / change envelope shape
$EDITOR contract/fixtures/<event>.json
python3 scripts/regen_golden.py       # regenerate contract/golden/
git diff contract/golden/             # REVIEW carefully
```

---

## Releasing

**One-time setup (enables signed auto-update):** run `python3 scripts/keygen.py`,
store the printed seed as the GitHub Actions secret `VIBEMON_SIGNING_SEED`, and
commit the updated `src/release_pubkey.py`. Until this is done the shipped client
is fail-closed: it will not auto-update (no unsigned exec), and releases fail at
the signing step.

1. Edit `VERSION` (e.g. `10` → `11`).
2. Run `python3 scripts/build.py`. Commit `dist/` + `VERSION`.
3. Tag: `git tag v11 && git push --tags`.
4. CI builds, tests, **signs** (`scripts/sign.py` → `install.sh.sig` /
   `install.ps1.sig`), and attaches the installers + `.sig` + `sha256sum.txt`
   to a GitHub Release.
5. `vibemon.dev/install.sh` (and `…/install.sh.sig`) redirect to the latest tag.

The `auto-update` mechanism inside `notify.sh` / `notify.py` polls the new release
once a day on `session_start`, **downloads the installer + its signature, verifies
it against the baked-in public key, and only then** re-runs `install.sh` when
VERSION bumps. A tampered or unsigned artifact is never executed.

> **Serving note:** `vibemon.dev` must serve/redirect `install.sh.sig` and
> `install.ps1.sig` alongside the installers (same 302-to-Release pattern). If the
> `.sig` is missing the client fails closed and skips the update.

---

## Reporting a vulnerability

See [SECURITY.md](SECURITY.md). TL;DR — email security@streamize.net,
do not file a public issue. We respond within 72 hours.

---

## License

MIT. See [LICENSE](LICENSE).
