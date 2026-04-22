# Changelog

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
