# Security Policy

`vibemon-hooks` runs on user machines under their shell account. We
take security findings seriously.

## Supported versions

Only the latest minor of the latest VERSION (the file at the repo root)
is supported. Older `dist/install.sh` artifacts are kept on GitHub
Releases for audit purposes only — the auto-update mechanism in
`notify.sh` will roll users forward within 24 hours of a new release.

## Reporting a vulnerability

**Do not file a public issue or pull request.**

Email **security@streamize.net** with:

- A description of the issue
- Steps to reproduce
- Affected version(s) (the `VERSION` file value or release tag)
- Your suggested fix, if any

We acknowledge within **72 hours** and aim to ship a patch within
**7 days** for critical issues. We will credit you in the release notes
unless you prefer to remain anonymous.

## Threat model

We design and test against:

- **Body leakage** — code or prompt content reaching the wire format.
  Mitigation: `tests/test_privacy_canary.py` runs in CI on every PR and
  every release.
- **Settings file corruption** — `~/.claude/settings.json` etc. being
  truncated, scrambled, or losing user-added hooks during a vibemon
  install. Mitigation: `flock` + `tempfile.mkstemp` + `os.replace`,
  plus `tests/test_install_idempotent.py` covering the merge cases.
- **Concurrent install races** — multiple agent sessions calling
  `notify.sh session_start` at the same time triggering simultaneous
  auto-updates. Mitigation: `mkdir`-based atomic lock at
  `~/.vibemon/update.lock`.
- **Distribution tampering** — `vibemon.dev/install.sh` serving content
  that doesn't match the committed `dist/install.sh`. Mitigation: the
  install URL is a 302 redirect to a GitHub Release artifact, which is
  immutable and matches the build for that tag.

We do **not** currently defend against:

- A compromised GitHub account pushing a malicious release. Releases
  are not yet signed (`cosign` integration is a planned follow-up).
  Pin to a known-good tag if you need stronger guarantees.
- A malicious AI agent manipulating the JSON it sends to `notify.sh` in
  a way that triggers unintended POSTs to the VibeMon backend. The
  envelope is sent regardless of payload — no data exfiltration vector
  exists since we strip bodies, but pathological inputs could still
  generate noise events.
