#!/usr/bin/env python3
"""
build.py — Reproducible build for vibemon-hooks.

Reads src/, substitutes # %%EMBED:filename%% markers (Unix install.sh)
and __PYTHON_BUNDLE_BASE64__ (Windows install.ps1) with the appropriate
embedded payloads. Writes:

    dist/install.sh        + dist/install.sh.sha256
    dist/install.ps1       + dist/install.ps1.sha256

Both outputs are byte-for-byte deterministic from the same inputs (no
timestamps, no random IDs, sorted tarball members, gzip mtime=0).

Usage:
    python3 scripts/build.py            # write both artifacts
    python3 scripts/build.py --check    # exit 1 if either is stale
"""

import argparse
import base64
import gzip
import hashlib
import io
import os
import re
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
DIST = os.path.join(ROOT, "dist")
VERSION_FILE = os.path.join(ROOT, "VERSION")

EMBED_RE = re.compile(r"^([ \t]*)# %%EMBED:([^%]+)%%[ \t]*$", re.MULTILINE)

# Python modules shipped to ~/.vibemon/ on Windows installs. Order matters
# only for tarball determinism — we sort before adding.
WINDOWS_BUNDLE_FILES = [
    "paths.py",
    "lock.py",
    "classify.py",
    "extract.py",
    "notify.py",
    "install.py",
    "merge_claude.py",
    "merge_gemini.py",
    "merge_cursor.py",
    "merge_codex.py",
]


def read(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return f.read()


def read_bytes(name):
    with open(os.path.join(SRC, name), "rb") as f:
        return f.read()


def substitute(template, providers):
    """Replace each `# %%EMBED:name%%` line with the matching provider() result.
    Preserves leading indentation of the marker line on every embedded line."""
    def repl(match):
        indent, name = match.group(1), match.group(2).strip()
        if name not in providers:
            raise KeyError(f"No provider for embed {name!r}")
        body = providers[name]()
        if indent:
            body = "\n".join(indent + line if line else line for line in body.split("\n"))
        return body
    return EMBED_RE.sub(repl, template)


def _read_version():
    if not os.path.exists(VERSION_FILE):
        return ""
    with open(VERSION_FILE, encoding="utf-8") as f:
        return f.read().strip()


# ─── Unix install.sh ──────────────────────────────────────────────────
def build_notify_sh():
    """Build the standalone notify.sh — embeds classify.py + extract.py."""
    template = read("notify.sh")
    providers = {
        "classify.py": lambda: read("classify.py").rstrip("\n"),
        "extract.py":  lambda: read("extract.py").rstrip("\n"),
    }
    return substitute(template, providers)


def build_install_sh():
    """Build the final dist/install.sh — embeds notify.sh + all merge_*.py.
    lock.py is embedded inside the claude/gemini heredocs so FileLock is in
    scope when merge_*.py's `from lock import FileLock` shim falls through."""
    template = read("install.sh")
    notify = build_notify_sh()
    providers = {
        "notify.sh":       lambda: notify.rstrip("\n"),
        "lock.py":         lambda: read("lock.py").rstrip("\n"),
        "merge_claude.py": lambda: read("merge_claude.py").rstrip("\n"),
        "merge_gemini.py": lambda: read("merge_gemini.py").rstrip("\n"),
        "merge_cursor.py": lambda: read("merge_cursor.py").rstrip("\n"),
        "merge_codex.py":  lambda: read("merge_codex.py").rstrip("\n"),
    }
    out = substitute(template, providers)

    version = _read_version()
    if version:
        out = out.replace("__VIBEMON_VERSION__", version)
    return out


# ─── Windows install.ps1 ──────────────────────────────────────────────
def build_python_bundle_b64():
    """Pack WINDOWS_BUNDLE_FILES into a deterministic gzipped tarball,
    return base64-encoded text wrapped at 76 chars per line.

    Determinism rules:
      - tar member order = sorted filenames
      - mtime=0, uid=0, gid=0, uname='', gname='', mode=0o644 on every member
      - gzip header mtime=0 (mtime=0 in GzipFile call)
    """
    raw = io.BytesIO()
    # gzip with mtime=0 — without this, gzip embeds wallclock and breaks reproducibility
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, compresslevel=9) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for name in sorted(WINDOWS_BUNDLE_FILES):
                data = read_bytes(name)
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mtime = 0
                info.mode = 0o644
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.type = tarfile.REGTYPE
                tar.addfile(info, io.BytesIO(data))
    encoded = base64.b64encode(raw.getvalue()).decode("ascii")
    # PowerShell here-string is happy with arbitrary line lengths; we wrap
    # at 76 chars so the script is reviewable in a terminal.
    return "\n".join(encoded[i:i + 76] for i in range(0, len(encoded), 76))


def build_install_ps1():
    """Build dist/install.ps1 — substitutes __VIBEMON_VERSION__ and
    __PYTHON_BUNDLE_BASE64__ in the PowerShell template."""
    template = read("install.ps1")
    bundle = build_python_bundle_b64()
    out = template.replace("__PYTHON_BUNDLE_BASE64__", bundle)
    version = _read_version()
    if version:
        out = out.replace("__VIBEMON_VERSION__", version)
    return out


# ─── Driver ───────────────────────────────────────────────────────────
def _write_artifact(path, content, mode=0o755):
    os.makedirs(DIST, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    sha = hashlib.sha256(content.encode()).hexdigest()
    with open(path + ".sha256", "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{sha}  {os.path.basename(path)}\n")
    return sha


def _check_artifact(path, content):
    if not os.path.exists(path):
        print(f"{path} missing — run `python3 scripts/build.py`", file=sys.stderr)
        return False
    with open(path, encoding="utf-8") as f:
        current = f.read()
    if current != content:
        cur_sha = hashlib.sha256(current.encode()).hexdigest()[:12]
        new_sha = hashlib.sha256(content.encode()).hexdigest()[:12]
        print(f"{path} is STALE (committed {cur_sha} vs built {new_sha})", file=sys.stderr)
        return False
    print(f"{path} is up to date ({hashlib.sha256(current.encode()).hexdigest()[:12]})")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="Exit 1 if any dist artifact is stale")
    args = parser.parse_args()

    sh_built  = build_install_sh()
    ps1_built = build_install_ps1()

    sh_path  = os.path.join(DIST, "install.sh")
    ps1_path = os.path.join(DIST, "install.ps1")

    if args.check:
        ok = True
        ok &= _check_artifact(sh_path,  sh_built)
        ok &= _check_artifact(ps1_path, ps1_built)
        if not ok:
            print("run `python3 scripts/build.py` and commit the result", file=sys.stderr)
            sys.exit(1)
        return

    sh_sha  = _write_artifact(sh_path,  sh_built,  mode=0o755)
    ps1_sha = _write_artifact(ps1_path, ps1_built, mode=0o644)

    print(f"built {sh_path}")
    print(f"  size: {len(sh_built)} bytes")
    print(f"  sha256: {sh_sha}")
    print(f"built {ps1_path}")
    print(f"  size: {len(ps1_built)} bytes")
    print(f"  sha256: {ps1_sha}")


if __name__ == "__main__":
    main()
