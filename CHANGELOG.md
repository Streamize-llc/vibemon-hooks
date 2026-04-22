# Changelog

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
