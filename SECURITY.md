# Security Policy

`vibemon-hooks` runs on user machines under their shell account. We
take security findings seriously.

## Supported versions

Only the latest minor of the latest VERSION (the file at the repo root)
is supported. Older `dist/install.sh` artifacts are kept on GitHub
Releases for audit purposes only — the auto-update mechanism in
`notify.sh` will roll users forward within 24 hours of a new release.

## How the auto-updater is secured (signed releases)

`notify.sh` / `notify.py` check for a new version once/day on session start. The
updater **never pipes a remote script to a shell.** It downloads the installer
**and a detached Ed25519 signature** (`install.sh.sig` / `install.ps1.sig`), then
verifies the bytes against a **public key baked into the client**
(`src/release_pubkey.py`) with a pure-stdlib verifier (`src/ed25519.py`) before
executing anything. Invalid signature, missing signature, or an unconfigured key
⇒ **nothing runs** (fail-closed).

The signing **secret seed** exists only as the GitHub Actions secret
`VIBEMON_SIGNING_SEED` and is never in the repo. A compromised `vibemon.dev` or
GitHub Release can swap the artifact bytes but **cannot forge a signature**, so a
tampered installer fails verification and is not executed. This closes the prior
unsigned-update channel (CWE-494). Correctness + fail-closed behavior are enforced
in CI by `tests/test_signature.py` (RFC 8032 known-answer vector, tamper
rejection, and a PyNaCl cross-check).

Key rotation: run `python3 scripts/keygen.py`, store the printed seed as the
`VIBEMON_SIGNING_SEED` secret, commit the updated `src/release_pubkey.py` + `dist/`,
and cut a release.

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

- **Distribution tampering / compromised release** — a malicious installer
  served from `vibemon.dev` or a GitHub Release (including via a compromised
  account or domain). Mitigation: **Ed25519-signed releases** verified by the
  client before execution (see "How the auto-updater is secured" above). Without
  the offline signing seed, a swapped artifact fails verification and never runs.

We do **not** currently defend against:

- A malicious AI agent manipulating the JSON it sends to `notify.sh` in
  a way that triggers unintended POSTs to the VibeMon backend. The
  envelope is sent regardless of payload — no data exfiltration vector
  exists since we strip bodies, but pathological inputs could still
  generate noise events.
