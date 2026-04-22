# Contributing

`vibemon-hooks` is small on purpose. Most changes fall into one of three
shapes — each has a checklist.

## 1. Adding a bash classifier rule

```bash
$EDITOR src/classify.py             # add the rule
$EDITOR tests/test_classify.py      # add at least one assertion
python3 scripts/build.py
python3 -m pytest tests/test_classify.py -v
```

Rule placement matters — more specific patterns must come before
generic catch-alls (e.g. `git.commit` before `git.other`).

## 2. Adding a new signal

```bash
$EDITOR src/extract.py              # emit the new key in derive_signals()
$EDITOR contract/envelope-v2.schema.json   # document the new property
$EDITOR SIGNALS.md                  # human-readable doc
$EDITOR tests/test_extract.py       # unit test for the new derivation
python3 scripts/regen_golden.py     # regenerate goldens
git diff contract/golden/           # REVIEW before committing
python3 -m pytest tests/
```

Ask: does this signal expose anything we promised not to send in
`PRIVACY.md`? If yes, add a canary fixture too.

## 3. Adding a new event type

Most events are already wired (`activity`, `bash`, `prompt`, `stop`,
`permission`, `tool_failure`, `session_start`, `session_end`). New
events are rare. If you must:

```bash
$EDITOR src/merge_claude.py         # register the hook with Claude Code
$EDITOR src/merge_gemini.py         # mirror for other agents
$EDITOR src/extract.py              # handle EVENT-specific signals
$EDITOR contract/fixtures/<event>.json
python3 scripts/regen_golden.py
$EDITOR contract/envelope-v2.schema.json   # add to event enum
python3 -m pytest tests/
```

The vibemon-app server's `/hook` function will need a matching handler —
file an issue or PR there too.

## Privacy contributions

Anything that touches the envelope shape, the sanitizer, or the
classifier needs:

- A new canary fixture if it could plausibly leak a string
- A passing canary test before merge
- A note in `PRIVACY.md` if it changes what categories of data we send

## Shipping a release

1. `VERSION` → bump
2. `python3 scripts/build.py`
3. Commit `VERSION` + `dist/install.sh` + `dist/install.sh.sha256`
4. `git tag vN && git push --tags`
5. Watch `release.yml` finish — it tests, builds, attaches install.sh
   to a GitHub Release.

## Don't

- Don't hand-edit `dist/install.sh`. The build will overwrite.
- Don't commit credentials or test API keys.
- Don't add Python dependencies — `extract.py` and friends must run
  on stock Python 3.6+ stdlib so they work on every user machine.
- Don't add bash-isms that break on macOS's older bash 3.2 (no
  associative arrays, no `${var,,}`). The CI matrix includes macOS to
  catch these.
