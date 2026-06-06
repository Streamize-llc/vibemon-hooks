# Changelog

## v24 — 2026-06-06

macOS GUI installer (Phase 1) + piped-install stdin fix.

### Why
Non-terminal users (vibe-coders on Cursor especially) had no install
path that didn't involve copy-pasting a shell one-liner. Separately,
while updating a machine via `curl … | sh` we found the install output
silently ended right after "Testing connection…".

### What changed
- **New `installer/macos/`** — "VibeMon Installer.app" (SwiftUI, single
  file, universal arm64+x86_64, ad-hoc signed). A deliberate *thin
  shell*: it downloads `https://vibemon.dev/install.sh` (the same
  auditable release artifact) and runs it with the pasted API key —
  zero install logic of its own, so hook merges, privacy guarantees,
  idempotency and daily auto-update are all inherited. Features:
  `vbm_` key validation, clipboard auto-prefill, Command Line Tools
  preflight (python3), streamed install log, restart-your-agent
  success screen. `release.yml` gains an `installer-macos` job that
  attaches `VibeMon-Installer.dmg` (+ sha256) to every release.
  Unsigned-by-decision for launch — macOS shows "Open Anyway" friction;
  Developer ID + notarization is the documented upgrade path.
- **install.sh section 6: `</dev/null` on the test probe.** In piped
  installs (`curl … | sh`) stdin is the pipe still holding the rest of
  the script; notify.sh's `cat > "$STDIN_FILE"` slurped it and the
  install silently ended at the connection test. Functionally harmless
  today (only the final echoes were lost) but a landmine for any future
  step added after section 6. Pinned by a static test.

## v23 — 2026-06-06

Auto-update actually works now — four compounding bugs fixed.

### Why
A production machine was found stuck on v18 for six weeks with an
orphaned `~/.vibemon/update.lock` from April. The investigation found
the entire auto-update path was broken on BOTH OSes, in four layers:

1. **The EXIT trap never released the lock (Unix root cause).**
   `local LOCK_DIR` + a single-quoted `trap 'rmdir "$LOCK_DIR"' EXIT`
   means the trap expands the variable when it FIRES — after the
   function has returned and the `local` is out of scope. Every check
   ran `rmdir ''` (a silent no-op), so the first daily check of every
   install left the lock behind and auto-update died permanently.
2. **No stale-lock recovery.** Once orphaned (by #1, or by a checker
   killed mid-flight by sleep/SIGKILL), `mkdir` fails forever and every
   future check returns immediately. No TTL, no self-heal.
3. **notify.py ran the check in a daemon thread.** The hook process
   exits within milliseconds (fire-and-forget by design), killing the
   thread mid-fetch and skipping the `finally` that releases the lock —
   invariant #5 ("a thread dies with the parent") applied to the lock
   lifecycle too.
4. **`iwr | iex` was a no-op.** notify.py's Windows updater pipes
   install.ps1 into `iex` with no arguments; the script only defined
   its functions and exited (the `if ($ApiKey)` guard never fired), so
   Windows auto-update never installed anything even when reached.

### What changed
- `notify.sh`: `LOCK_DIR` is no longer `local` (the trap can see it);
  stale locks older than 60 minutes are removed and re-acquired
  (`find -mmin +60` — BSD + GNU compatible); lock contention returns 0.
- `notify.py`: same 60-minute TTL via `os.stat` mtime; the check now
  runs in a detached `__update_check` helper process (spawned like the
  POST helper) with a guaranteed try/finally, replacing the daemon
  thread.
- `install.ps1`: piped-iex with a stored `~/.vibemon/api-key` now runs
  the update with that key (`return`, not `exit`, so an interactive
  caller's shell survives). Fresh machines keep the interactive
  `vibemon-install YOUR_API_KEY` flow.
- Tests: new `tests/test_update_lock.py` (8 tests) — Python lock
  semantics (TTL recovery / fresh-lock respect / release), process
  model (session_start must spawn the detached helper; `__update_check`
  sends no envelope), and the bash function executed for real from the
  built artifact, pinning the trap-release root cause.

Already-stuck installs cannot self-heal (their old notify skips the
check before fetching anything) — they need one manual re-install,
after which the v23 logic keeps them current forever. An app-side
"update available" nudge using `script_install_status` is the
follow-up.

## v22 — 2026-06-06

HEREDOC commit titles survive quote characters in the body.

### Why
v18 fixed `commit.message` capturing the literal `$(cat <<'EOF'` opener,
but only for *clean* bodies. Production data (including this repo's own
v21 release commit) showed two surviving failure modes, both triggered
by quote characters inside the HEREDOC body:

1. **Double-quoted phrases** (`mask "no data" instead`) — each `"`
   toggles shlex's quote state mid-body, so the `-m` token ends at the
   first unquoted whitespace *before* the closing DELIM. The heredoc
   regex then fails and the literal opener came back as the title.
2. **Odd quote count** (an apostrophe or `"` landing in an unquoted
   stretch) — shlex aborts with "unclosed quote", the whole command's
   tokens were dropped, and the event lost BOTH its title and its
   `git.commit` category (`bash.category` = `""` → commit silently
   uncounted downstream).

### What changed
- `classify.py extract_commit_message`: when the `-m` token comes back
  truncated at the opener (or tokenization lost the argument), fall back
  to searching the **raw command string** with a flag-anchored regex
  (`-m` / `-am` / `--message[=]` immediately followed by `$(cat <<`).
  The anchor guarantees only the heredoc that IS the message argument
  can match — a heredoc belonging to another command in the chain can
  never be read (privacy invariant preserved), and the literal opener
  can never be returned again.
- `classify.py _chain_token_segments`: on mid-stream tokenization abort
  (unclosed quote), keep the in-flight segment's tokens so
  `git commit -m "$(…odd quotes…)"` still classifies as `git.commit`.
- Tests: +9 covering quoted phrases, unbalanced quotes, chains,
  body-mentions-`git commit -m`, foreign-heredoc-never-stolen, and a
  distilled reproduction of the actual v21 release commit. New contract
  fixture + golden (`bash_git_commit_heredoc_quoted`) locks the case
  end-to-end through both runtimes; all existing goldens byte-unchanged.

## v21 — 2026-06-06

MCP server registration (Phase 2) + hook-merge locking parity.

### Why
The vibemon MCP server (`https://vibemon.dev/api/mcp`, Streamable HTTP)
lets AI agents read and write team TODOs using the same `vbm_*` key the
hooks already use. Until now the only path was a manual `claude mcp add`
/ hand-editing `~/.cursor/mcp.json` — error-prone and never updated on
key rotation. While wiring the installer up, the cursor and codex hook
merges were found writing settings with a bare `open("w")` — a
violation of the multi-session FileLock invariant that the
claude/gemini merges already followed.

### What changed
- **New `src/merge_mcp.py`** — idempotently registers `mcpServers.vibemon`
  in Claude Code's `~/.claude.json` (user scope,
  `{"type": "http", url, headers}` — the same shape
  `claude mcp add --transport http` writes) and Cursor's
  `~/.cursor/mcp.json` (`{url, headers}` only; Cursor's docs don't define
  a `type` for remote servers). Key rotation updates the Authorization
  header in place; other `mcpServers` entries and all unrelated config
  are preserved. Unparseable JSON → registration is skipped and the file
  left untouched — these are *not* vibemon-owned files, so "treat as
  empty and overwrite" (what the hook merges do for their own settings)
  would destroy Claude Code's entire user state.
- `install.sh` section 5e (Unix) **and** `install.py` (Windows) both
  register — OS parity from day one; `merge_mcp.py` ships in the
  Windows bundle.
- `merge_cursor.py` / `merge_codex.py` now use the same exclusive
  FileLock + `tempfile.mkstemp` + `os.replace` pattern as claude/gemini
  (multi-session invariant #3); previously a direct `open("w")` could
  truncate-race under concurrent installs.
- Claude Code `PostToolUseFailure` gains a `Bash` matcher — failed
  tests/builds now fire `tool_failure`. `PostToolUse` and
  `PostToolUseFailure` are mutually exclusive (success vs failure), so
  there is no double-count with the `bash` event.
- Installer prints a "restart your agent session" hint (a running
  Claude Code / Cursor doesn't reload MCP config mid-session).
- `notify.py`: dropped the dead `raw_stdin_was_text` parameter from
  `_fire`.
- Tests: new `tests/test_merge_mcp.py` (idempotency, key rotation,
  preservation of foreign state, corrupt-JSON skip, lock sentinel name);
  `test_static.py` now *executes* every embedded `PYMERGE_*` heredoc
  against a temp config with the exact argv `install.sh` passes —
  py_compile can't catch a missing `lock.py` embed (runtime
  `NameError: FileLock`), execution can.

## v20 — 2026-05-07

`tool.duration_ms` signal — cross-agent normalization.

### What changed
- PostToolUse `duration_ms` (Claude Code v2.1.119+) and Cursor's
  `duration` (also ms) were silently dropped by the `SAFE_TOP_KEYS`
  allowlist; both are now allowed and normalized into
  `signals["tool.duration_ms"]`.
- Gemini CLI and Codex CLI provide neither — their events carry
  `tool.duration_unavailable: true` so analytics can distinguish
  "no data" from "instant tool".
- Only emitted on `activity` / `tool_failure` events; bool/string
  values rejected. New fixtures cover both wire formats; existing
  goldens regenerated with the unavailable flag.

## v19 — 2026-04-30

Fix: IANA timezone names instead of abbreviations.

### What changed
- `local_time_fields()` returned `str(tzinfo)` abbreviations ("KST",
  "EST") — invalid for server-side `Intl.DateTimeFormat`, silently
  falling every non-Korean user back to Asia/Seoul.
- New `_iana_tz()` reads the `/etc/localtime` symlink (macOS/Linux),
  `/etc/timezone` (Debian), or `$TZ` to return proper IANA names
  ("Asia/Seoul", "America/New_York").

## v18 — 2026-04-25

HEREDOC commit-message parsing + env-var prefix secret mask. Two
production-data fixes discovered by auditing `hook_events.signals`.

### What changed
- `extract_commit_message`: agents (notably Claude Code) pass commit
  titles via a command-substitution HEREDOC; the old tokenizer stored
  the literal heredoc opener as the title. New `_HEREDOC_RE` +
  `_extract_message_from_arg` pull the first non-empty body line,
  keep the 200-char cap, and support `<<-`, quoted and custom
  delimiters.
- `bash.head`: naive `cmd.split()[0]` leaked env-var **values** for
  `KEY=value cmd …` prefixed commands. New `safe_command_head()` skips
  `KEY=VAL` tokens shlex-aware and returns `<env>` when the command is
  nothing but assignments; same skip applied in `_classify_single` and
  `_commit_message_from_tokens`.
- +22 pytest cases covering every HEREDOC variant seen in production.

## v17 — 2026-04-24

Hot-fix follow-up to v16 — explicit `encoding="utf-8"` on every text
`open()` call so build/install/notify work on Windows where the default
codec is cp1252.

### Why
v16's CI matrix added `windows-latest` and immediately failed:
`UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d` while
reading `src/install.sh` (contains `🐾`, `→`, `…`). Same bug would
have hit Windows users running `notify.py` against any settings.json
or config file containing non-ASCII bytes (Korean prompts, em dashes).

### What changed
- `scripts/build.py`, `scripts/regen_golden.py`: read sources with
  `encoding="utf-8"`, write artifacts with `encoding="utf-8", newline="\n"`
  (locks dist file bytes regardless of OS).
- `src/notify.py`, `src/install.py`, `src/extract.py`, `src/lock.py`,
  `src/merge_*.py`: all `open()` and `os.fdopen()` text-mode calls now
  pass `encoding="utf-8"` explicitly.
- Tests: same fix for fixture/golden/canary loads.

No behavior change on macOS / Linux — UTF-8 is already the default
codec there. Hash of `dist/install.sh` differs from v16 only because
of the VERSION token.

## v16 — 2026-04-24

Windows native installer (`install.ps1`) — Unix path unchanged.

### Why
Until v15 the installer was bash-only. Native Windows users (Claude
Code / Cursor / Codex on Windows, no WSL) had no install path — `bash`,
`fcntl`, `disown`, and `mkdir -p ~/.vibemon` are all Unix-isms baked
into `install.sh` and `notify.sh`. v16 ships a parallel PowerShell
installer + Python `notify.py` runtime that produces byte-identical
envelopes, while leaving the Unix path completely untouched.

### What changed
- **New Windows runtime** (Python stdlib only):
  - `src/notify.py` — full port of `notify.sh`. urllib instead of curl,
    `subprocess.Popen(start_new_session=True/DETACHED_PROCESS)` instead
    of `& disown` for SIGHUP-immune fire-and-forget.
  - `src/install.py` — installer runner invoked by `install.ps1`.
  - `src/install.ps1` — PowerShell shim. Detects `py`/`python3`/`python`,
    extracts an embedded base64 tarball into `%USERPROFILE%\.vibemon\`,
    restricts api-key ACL via `icacls`.
  - `src/paths.py` — single source of OS-aware paths and python launcher
    detection.
  - `src/lock.py` — cross-platform exclusive `FileLock` (fcntl on Unix,
    `msvcrt.locking` on Windows). Used by `merge_*.py` for the
    settings.json multi-session safety invariant.
- **Unix runtime preserved**: `install.sh` and `notify.sh` are
  unchanged in shape. `merge_*.py` were refactored to accept an
  optional `notify_prefix` parameter (defaults to the existing
  `bash ~/.vibemon/notify.sh` command), so the hook commands written
  to `~/.claude/settings.json` etc. on Unix are byte-identical to v15.
- **Build** (`scripts/build.py`):
  - Now emits both `dist/install.sh` and `dist/install.ps1`, each with
    a `.sha256` companion.
  - Windows bundle is a deterministic gzipped tarball (mtime=0,
    sorted member order, uid=gid=0) base64-encoded into the .ps1
    template. Two consecutive builds produce identical sha256.
- **Tests**: 68 → 94.
  - `test_paths.py` (7) — OS-aware path helpers.
  - `test_lock.py` (3) — `FileLock` serializes concurrent writers,
    releases on exception.
  - `test_envelope_parity.py` (10) — `notify.py` and `notify.sh`
    produce JSON-equivalent envelopes for every fixture.
  - `test_install_idempotent.py` (+6) — Windows-style `notify_prefix`
    cases; bash↔Python re-install swap is clean (substring `vibemon`
    match catches both forms).
- **CI**: `windows-latest` matrix added (Python 3.10 + 3.12). PowerShell
  AST parser validates `dist/install.ps1` syntax. Dry-install verifies
  bundle extraction and `notify.py` py_compile.
- **Web**: `vibemon-web/src/app/install.ps1/route.ts` — 302 redirect
  to the GitHub Release artifact, mirror of the existing
  `install.sh/route.ts`.

### Compatibility
- macOS / Linux users on v15 → v16 auto-update: zero behavior change.
  The hook command strings in `settings.json` stay
  `bash ~/.vibemon/notify.sh ...`. `notify.sh` is unchanged. The only
  diff is `dist/install.sh` rebuilds with the new `lock.py` embedded
  inside the merge heredocs (Linux `FileLock` wraps `fcntl.flock` —
  same syscall, same semantics).
- Windows native install:
  `iwr -useb https://vibemon.dev/install.ps1 | iex; vibemon-install YOUR_API_KEY`
- Same Supabase URL, same envelope schema, same auto-update mechanism
  (notify.py uses the right installer per OS on session_start).

### Privacy
No new signals, no envelope shape change. Privacy canary suite still
passes on the new Python runtime — `extract.py` and `classify.py` are
unchanged.

## v15 — 2026-04-24

Shell-chain support: agent-issued commands like `git add . && git
commit -m "feat: x" && git push` now classify as `git.commit` (not
`git.other`) and extract the commit message title.

### Why
v13/v14 matched commit commands on `tokens[0] == "git" && tokens[1] ==
"commit"`. Claude Code / Cursor / Gemini CLI routinely emit chained
commands as a single Bash tool call — `git add . && git commit -m "…"
&& git push` — where the first token is `git add`. The chain was
silently dropped from commit-message collection, so the Commit Tape
feature saw empty data from agent-driven sessions in the wild.

### What changed
- `classify.py` tokenizes with
  `shlex.shlex(punctuation_chars=True)` — a stdlib-only approach.
  Chain separators (`&&`, `||`, `;`, `|`, newline) become their own
  tokens; quoted separators inside `git commit -m "feat && fix"` stay
  in the message token (POSIX quoting from stdlib, no hand-rolled
  state machine).
- `classify_bash` classifies each chain segment and picks the
  highest-priority category from `_CHAIN_PRIORITY` (git.commit >
  deploy > git.push > test.run > …). No priority match → first
  segment's classification.
- `extract_commit_message` iterates the same tokenized segments,
  parsing `-m` / `--message=` / combined short flags (`-am`, `-ma`)
  on whichever segment starts with `git commit`.
- Tests: 58 → 68. New `test_chain_tokens_*`, `test_chain_*`, and
  `test_extract_commit_message_chain` cases cover `&&`/`;` chains,
  quoted separator preservation, priority ordering, and the canary
  still-doesn't-leak invariant on chained input.

### Privacy
No new data captured — just unlocks the title extraction path that
v14 already documented. Multi-line commit bodies are still discarded.
Existing privacy canary suite still passes on chained fixtures.

## v14 — 2026-04-24

Expose commit message collection as an explicit install-time flag so the
VibeMon app/web onboarding can surface it as a plain toggle.

### What changed
- `install.sh` now accepts positional API key + optional flags:
  - `--no-commit-msg` writes `no_commit_msg=1` into `~/.vibemon/config`
  - `--collect-commit-msg` writes the commented-out form (explicit opt-in)
  - No flag on re-install = preserve existing config as-is
- App `SetupWizard` renders a checkbox under the terminal. Toggling it
  appends/removes `--no-commit-msg` in the copy-to-clipboard command —
  the command the user pastes is always self-sufficient.
- Web `/setup` page mirrors the same toggle. The landing-page
  `InstallSection` stays static (its command uses the `YOUR_API_KEY`
  placeholder and links users through to `/setup` for the real flow).

### Why
v13 made commit-message collection default-on with a hidden opt-out
file. Onboarding needed to make the choice visible before install,
without introducing a server-side toggle + polling system. CLI flag +
UI toggle = zero extra network state, one command line diff.

## v13 — 2026-04-23

Collect git commit message titles by default to power the activity feed.

### What changed
- `classify.py` gains `extract_commit_message(cmd)` — shlex-tokenizes
  the command, pulls the message from `-m` / `--message=` / `-am`
  variants, keeps the first line only, caps at 200 characters.
- `extract.py` emits `signals.commit.message` when `bash.category ==
  "git.commit"`, unless the env var `VIBEMON_NO_COMMIT_MSG=1` is set.
- `notify.sh` reads `~/.vibemon/config` (simple `key=value`) and passes
  `no_commit_msg=1` through as `VIBEMON_NO_COMMIT_MSG`. No network
  call needed; flip takes effect on the next hook fire.
- `install.sh` creates `~/.vibemon/config` on first install (never
  overwrites existing) and prints an opt-out notice at the end of the
  first install run.
- Envelope schema adds `commit.message` (maxLength 200).

### Privacy
- PRIVACY.md updated: commit-message collection is now an explicit
  documented exception to the "no command bodies" rule. Multi-line
  commit bodies are still always discarded — only the title leaves the
  machine.
- Existing privacy canary tests still pass (secret-in-`echo` still
  never leaks; only `-m "…"` titles are extracted).

## v12 — 2026-04-22

Bake the Supabase project URL into the install scripts so `vibemon.dev`
can serve `install.sh` as a pure 302 redirect to the GitHub Release
artifact — no server-side fetch, no risk of edge-function timeout.

### Why
v11 deployed via `vibemon-web/install.sh/route.ts` doing a server-side
`fetch` against the GitHub Release. Vercel's edge function repeatedly
hit `FUNCTION_INVOCATION_TIMEOUT` against `releases/latest/download/...`
(redirect chain), serving HTTP 504 to every install request.

### What changed
- `src/install.sh` and `src/notify.sh` now have the full Supabase URL
  (`https://sirpdtcwawcidhgtltps.supabase.co`) hardcoded. This URL is
  already public — exposed via `NEXT_PUBLIC_SUPABASE_URL` on the website
  and embedded in the mobile app binary.
- The `__SUPABASE_URL__` placeholder is gone.
- `install.sh` no longer needs a final `sed` to patch notify.sh.

### Distribution implication
`vibemon.dev/install.sh` becomes a 302 → GitHub Release. Users see the
real `github.com/Streamize-llc/vibemon-hooks` URL in their terminal,
which is a stronger trust signal than a proxy.

## v11 — 2026-04-22

Auto-update hardening — `notify.sh` now follows redirects on the version
probe (`?v`) and validates the response shape before re-running install.

### Bug fix
- `curl -sf "https://vibemon.dev/install.sh?v"` did not pass `-L`, so when
  the apex domain 307-redirects to `www.vibemon.dev` (default Vercel
  behavior), the probe returned the literal HTML body `"Redirecting..."`.
  The version compare then always evaluated as "different" but the install
  fetch (which DID use `-fsSL`) succeeded — so no harm except that the
  probe was effectively useless. Now uses `-fsSL` consistently.

### Defense in depth
- Version compare now rejects values longer than 16 chars before triggering
  a re-install. If the probe ever returns garbage again, we don't blindly
  pipe an unknown payload to `bash -s`.

## v10 — 2026-04-22

Initial extraction of `vibemon-hooks` as a separate, public, audit-friendly
repo. Functionally equivalent to the install scripts that previously lived
in `vibemon-app/supabase/functions/install/index.ts` and
`vibemon-web/src/app/install.sh/route.ts`, with the following improvements:

### Infrastructure
- Plain bash + Python source files (`src/install.sh`, `src/notify.sh`,
  `src/extract.py`, `src/classify.py`, `src/merge_*.py`) — no more
  TypeScript-array embedding.
- Reproducible build (`scripts/build.py --check`) — committed
  `dist/install.sh` must match a fresh build on every PR.
- Test suite: 58 tests covering classifier rules, signal extraction,
  envelope contract, settings.json merging, privacy canaries, and
  bash/python static checks.
- GitHub Actions on Ubuntu + macOS, Python 3.10 + 3.12.

### Bug fixes (from extraction)
- `classify_failure("String to replace not found")` now correctly
  returns `"string_mismatch"` instead of `"file_not_found"`. The old
  ordering matched the generic substring first. Same fix needs to land
  in `vibemon-app/supabase/functions/hook/index.ts`'s
  `extractServerSignals()`.

### Distribution
- Primary URL: `https://vibemon.dev/install.sh` (302 → GitHub Release).
- Pinned URL: `https://github.com/Streamize-llc/vibemon-hooks/releases/download/v10/install.sh`.
- Auto-update target inside `notify.sh` switched from
  `$SUPABASE_URL/functions/v1/install` to `https://vibemon.dev/install.sh`.

### Notes
- VERSION file is the single source of truth — both notify.sh's update
  check and the install.sh greeting read it.
- The release CI verifies tag matches VERSION before publishing.
