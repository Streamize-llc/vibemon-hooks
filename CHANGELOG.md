# Changelog

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
