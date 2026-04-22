#!/usr/bin/env python3
"""
build.py — Reproducible build for vibemon-hooks.

Reads src/, substitutes # %%EMBED:filename%% markers with file contents,
writes dist/install.sh. The output is byte-for-byte deterministic from
the same inputs (no timestamps, no random IDs).

Usage:
    python3 scripts/build.py            # write dist/install.sh
    python3 scripts/build.py --check    # exit 1 if dist/install.sh is stale
"""

import argparse
import os
import re
import sys
import hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
DIST = os.path.join(ROOT, "dist")
VERSION_FILE = os.path.join(ROOT, "VERSION")

EMBED_RE = re.compile(r"^([ \t]*)# %%EMBED:([^%]+)%%[ \t]*$", re.MULTILINE)


def read(name):
    with open(os.path.join(SRC, name)) as f:
        return f.read()


def substitute(template, providers):
    """Replace each `# %%EMBED:name%%` line with the matching provider() result.
    Preserves leading indentation of the marker line on every embedded line."""
    def repl(match):
        indent, name = match.group(1), match.group(2).strip()
        if name not in providers:
            raise KeyError(f"No provider for embed {name!r}")
        body = providers[name]()
        # Preserve indentation by prefixing each line with the same whitespace.
        if indent:
            body = "\n".join(indent + line if line else line for line in body.split("\n"))
        return body
    return EMBED_RE.sub(repl, template)


def build_notify_sh():
    """Build the standalone notify.sh — embeds classify.py + extract.py."""
    template = read("notify.sh")
    providers = {
        "classify.py": lambda: read("classify.py").rstrip("\n"),
        "extract.py":  lambda: read("extract.py").rstrip("\n"),
    }
    return substitute(template, providers)


def build_install_sh():
    """Build the final dist/install.sh — embeds notify.sh + all merge_*.py."""
    template = read("install.sh")
    notify = build_notify_sh()
    providers = {
        "notify.sh":       lambda: notify.rstrip("\n"),
        "merge_claude.py": lambda: read("merge_claude.py").rstrip("\n"),
        "merge_gemini.py": lambda: read("merge_gemini.py").rstrip("\n"),
        "merge_cursor.py": lambda: read("merge_cursor.py").rstrip("\n"),
        "merge_codex.py":  lambda: read("merge_codex.py").rstrip("\n"),
    }
    out = substitute(template, providers)

    version = ""
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE) as f:
            version = f.read().strip()
    if version:
        out = out.replace("__VIBEMON_VERSION__", version)

    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="Exit 1 if dist/install.sh differs from a fresh build")
    args = parser.parse_args()

    built = build_install_sh()
    out_path = os.path.join(DIST, "install.sh")

    if args.check:
        if not os.path.exists(out_path):
            print("dist/install.sh missing — run `python3 scripts/build.py`", file=sys.stderr)
            sys.exit(1)
        with open(out_path) as f:
            current = f.read()
        if current != built:
            cur_sha = hashlib.sha256(current.encode()).hexdigest()[:12]
            new_sha = hashlib.sha256(built.encode()).hexdigest()[:12]
            print(f"dist/install.sh is STALE (committed {cur_sha} vs built {new_sha})", file=sys.stderr)
            print("run `python3 scripts/build.py` and commit the result", file=sys.stderr)
            sys.exit(1)
        print(f"dist/install.sh is up to date ({hashlib.sha256(current.encode()).hexdigest()[:12]})")
        return

    os.makedirs(DIST, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(built)
    os.chmod(out_path, 0o755)

    sha = hashlib.sha256(built.encode()).hexdigest()
    sha_path = out_path + ".sha256"
    with open(sha_path, "w") as f:
        f.write(f"{sha}  install.sh\n")

    print(f"built {out_path}")
    print(f"  size: {len(built)} bytes")
    print(f"  sha256: {sha}")


if __name__ == "__main__":
    main()
