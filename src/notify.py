"""
notify.py — VibeMon agent hook thin client (cross-platform).

Functional twin of notify.sh. Used by the Windows installer (install.ps1)
which writes hook commands like:

    "py" "C:\\Users\\<user>\\.vibemon\\notify.py" activity claude_code

Fired by Claude Code / Gemini CLI / Cursor / Codex. Sanitizes the payload,
derives behavioral signals, POSTs the envelope to /hook.

Privacy invariants enforced by tests/test_privacy_canary.py.
Wire format byte-equivalent to notify.sh — verified by
tests/test_envelope_parity.py.

Stdlib only.
"""

import datetime
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request


# When this file is imported as a module (tests, install.py) the sibling
# files live in src/. When executed directly from ~/.vibemon/, all the
# helper modules are extracted alongside it.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from extract import build_envelope  # noqa: E402

# Public Supabase functions URL — same hardcoded constant as notify.sh.
API_URL = "https://sirpdtcwawcidhgtltps.supabase.co/functions/v1"

IS_WINDOWS = os.name == "nt"


# ─── State files ────────────────────────────────────────────────────
def _vibemon_dir():
    return os.path.join(os.path.expanduser("~"), ".vibemon")


def _read_text(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, IOError):
        return default


def _read_config():
    """Parse ~/.vibemon/config — `key=value` lines, # comments. Same grammar
    as notify.sh's `case "$_key" in ...` loop."""
    cfg = {}
    p = os.path.join(_vibemon_dir(), "config")
    if not os.path.exists(p):
        return cfg
    try:
        with open(p) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    except (OSError, IOError):
        pass
    return cfg


# ─── Project root detection ─────────────────────────────────────────
def _git(args, timeout=2):
    try:
        return subprocess.check_output(
            ["git"] + args,
            stderr=subprocess.DEVNULL,
            cwd=os.getcwd(),
            timeout=timeout,
        ).decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def _detect_project_root():
    """Match the bash version's three-tier detection:
    1. owner/repo from `git remote get-url origin`
    2. basename of git toplevel
    3. empty string"""
    url = _git(["remote", "get-url", "origin"])
    if url:
        if url.endswith(".git"):
            url = url[:-4]
        if "://" in url:
            # https://github.com/owner/repo
            parts = url.rstrip("/").split("/")
            if len(parts) >= 2:
                return "%s/%s" % (parts[-2], parts[-1])
        elif ":" in url:
            # git@github.com:owner/repo
            return url.split(":", 1)[1]
    root = _git(["rev-parse", "--show-toplevel"])
    if root:
        return os.path.basename(root)
    return ""


# ─── Auto-update (session_start, mkdir-locked, daily) ───────────────
def _auto_update_once():
    """Atomic mkdir-based lock — directory creation is atomic on POSIX
    and NTFS. Identical semantics to notify.sh's `mkdir "$LOCK_DIR"`.
    Multi-session invariant #4."""
    vd = _vibemon_dir()
    lock_dir = os.path.join(vd, "update.lock")
    try:
        os.mkdir(lock_dir)
    except FileExistsError:
        return
    except OSError:
        return
    try:
        last_path = os.path.join(vd, "last-update-check")
        now = int(time.time())
        if os.path.exists(last_path):
            try:
                last = int(_read_text(last_path, "0"))
                if now - last < 86400:
                    return
            except ValueError:
                pass
        try:
            with open(last_path, "w") as f:
                f.write(str(now))
        except (OSError, IOError):
            pass

        try:
            req = urllib.request.Request(
                "https://vibemon.dev/install.sh?v",
                headers={"User-Agent": "vibemon-notify"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                latest = r.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return

        if not latest or len(latest) > 16:
            return
        current = _read_text(os.path.join(vd, "version"), "")
        if latest == current:
            return

        # Spawn the appropriate self-updater detached so the parent hook
        # returns immediately. PowerShell on Windows, bash on Unix.
        try:
            if IS_WINDOWS:
                cmd = [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command",
                    "iwr -useb https://vibemon.dev/install.ps1 | iex",
                ]
            else:
                cmd = ["bash", "-c", "curl -fsSL https://vibemon.dev/install.sh | bash"]
            _spawn_detached(cmd, payload=None)
        except Exception:
            pass
    finally:
        try:
            os.rmdir(lock_dir)
        except OSError:
            pass


# ─── Detached subprocess helper (SIGHUP-immune fire-and-forget) ─────
# Multi-session invariant #5: notify.sh uses `& disown </dev/null` so the
# HTTP POST survives the agent process exiting immediately after firing
# the hook (critical for session_end). The Python equivalent is:
#   - POSIX: start_new_session=True → child is its own session leader,
#     no controlling tty, no SIGHUP on parent exit
#   - Windows: DETACHED_PROCESS | CREATE_NO_WINDOW → child detaches from
#     the parent console / job, survives parent exit
# Both also redirect stdio to DEVNULL to prevent pipe-death signals.
DETACHED_PROCESS = 0x00000008      # Windows: don't inherit parent console
CREATE_NO_WINDOW = 0x08000000      # Windows: don't pop up a console window


def _spawn_detached(cmd, payload=None):
    kwargs = dict(
        stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if IS_WINDOWS:
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    p = subprocess.Popen(cmd, **kwargs)
    if payload is not None:
        try:
            p.stdin.write(payload)
            p.stdin.close()
        except (OSError, BrokenPipeError):
            pass
    return p


def _spawn_post(body, api_key, version):
    """Spawn a tiny standalone Python that POSTs and exits — the equivalent
    of `(curl ... &) & disown` in notify.sh. The helper inherits no fds
    from us so even if our process dies the POST can complete."""
    helper = (
        "import sys, urllib.request\n"
        "data = sys.stdin.buffer.read()\n"
        "req = urllib.request.Request(\n"
        "    %r + '/hook',\n"
        "    data=data, method='POST',\n"
        "    headers={\n"
        "        'Content-Type': 'application/json',\n"
        "        'Authorization': 'Bearer ' + %r,\n"
        "        'X-Vibemon-Version': %r,\n"
        "    },\n"
        ")\n"
        "try:\n"
        "    urllib.request.urlopen(req, timeout=10).read()\n"
        "except Exception:\n"
        "    pass\n"
    ) % (API_URL, api_key, version)
    _spawn_detached([sys.executable, "-c", helper], payload=body)


# ─── Envelope build ─────────────────────────────────────────────────
def _utc_iso():
    """Match notify.sh's `date -u +%Y-%m-%dT%H:%M:%SZ` exactly."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_stdin_payload():
    if sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
    except (OSError, IOError):
        return {}
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return {}


def _fire(event, agent, payload, raw_stdin_was_text=True):
    """Build envelope, POST to /hook. Returns 0 on success, 1 on test
    probe failure. For non-test events, returns 0 immediately after
    spawning the detached POST."""
    cwd = os.getcwd()
    ts = _utc_iso()
    project_root = _detect_project_root()

    # Honor user opt-out via ~/.vibemon/config
    cfg = _read_config()
    if cfg.get("no_commit_msg") == "1":
        os.environ["VIBEMON_NO_COMMIT_MSG"] = "1"

    env = build_envelope(event, payload, agent, cwd, ts, project_root)
    body = json.dumps(env, ensure_ascii=False).encode("utf-8")

    api_key = _read_text(os.path.join(_vibemon_dir(), "api-key"))
    if not api_key:
        sys.stderr.write("[vibemon] API key not found at %s\n"
                         % os.path.join(_vibemon_dir(), "api-key"))
        return 1
    version = _read_text(os.path.join(_vibemon_dir(), "version"), "0")

    if event == "test":
        # Synchronous probe — connection check.
        req = urllib.request.Request(
            API_URL + "/hook",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + api_key,
                "X-Vibemon-Version": version,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    print("[vibemon] ✓ Connection successful")
                    return 0
                sys.stderr.write("[vibemon] ✗ Connection failed (HTTP %d)\n" % r.status)
                return 1
        except urllib.error.HTTPError as e:
            sys.stderr.write("[vibemon] ✗ Connection failed (HTTP %d)\n" % e.code)
            return 1
        except Exception as e:
            sys.stderr.write("[vibemon] ✗ Connection failed: %s\n" % e)
            return 1

    _spawn_post(body, api_key, version)

    # Gemini CLI requires JSON stdout to allow the hook to proceed.
    if agent == "gemini_cli":
        sys.stdout.write(json.dumps({"decision": "allow"}))

    return 0


# ─── Entry point ────────────────────────────────────────────────────
def main(argv=None):
    argv = argv if argv is not None else sys.argv
    event = argv[1] if len(argv) > 1 else "unknown"
    agent = argv[2] if len(argv) > 2 else "claude_code"

    if event == "session_start":
        # Non-blocking auto-update check. The thread is daemonic so it
        # cannot prevent process exit — but the actual install spawn is
        # a fully detached subprocess inside _auto_update_once, so the
        # update completes even after this process dies.
        threading.Thread(target=_auto_update_once, daemon=True).start()

    payload = _read_stdin_payload()
    return _fire(event, agent, payload)


if __name__ == "__main__":
    sys.exit(main())
