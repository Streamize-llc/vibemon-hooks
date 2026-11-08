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
import re
import subprocess
import sys
import tempfile
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
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, IOError, UnicodeDecodeError):
        return default


def _read_config():
    """Parse ~/.vibemon/config — `key=value` lines, # comments. Same grammar
    as notify.sh's `case "$_key" in ...` loop."""
    cfg = {}
    p = os.path.join(_vibemon_dir(), "config")
    if not os.path.exists(p):
        return cfg
    try:
        with open(p, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    except (OSError, IOError, UnicodeDecodeError):
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
    Multi-session invariant #4.

    Runs inside the detached __update_check helper process (see main());
    never call from a daemon thread — the thread dies with the parent and
    skips the finally, orphaning the lock."""
    vd = _vibemon_dir()
    lock_dir = os.path.join(vd, "update.lock")
    try:
        os.mkdir(lock_dir)
    except FileExistsError:
        # Stale-lock recovery (v23) — same 60-minute TTL as notify.sh.
        # A holder that died before its finally (crash / kill) must not
        # disable auto-update forever.
        try:
            if time.time() - os.stat(lock_dir).st_mtime < 3600:
                return
            os.rmdir(lock_dir)
            os.mkdir(lock_dir)
        except OSError:
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
            with open(last_path, "w", encoding="utf-8") as f:
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
        "    urllib.request.urlopen(req, timeout=30).read()\n"
        "except Exception:\n"
        "    pass\n"
    ) % (API_URL, api_key, version)
    _spawn_detached([sys.executable, "-c", helper], payload=body)


# ─── Coalescing (v31) — twin of notify.sh's spool ───────────────────
# bash + activity fire on every tool call and were ~88% of all /hook
# traffic; one edge-function invocation each got the Supabase org
# restricted on 2026-09-29. A session sends those two at most once per
# COALESCE_WINDOW; later ones wait in a per-session spool and ride along
# with the next send as {"batch":[…]}, which /hook replays in order with
# each envelope's own timestamp. Every other event goes out immediately.
COALESCE_WINDOW = 60
COALESCE_MAX = 50
COALESCED_EVENTS = ("bash", "activity")
ORPHAN_SPOOL_SECONDS = 600


def _spool_paths(env):
    sid = str(env.get("session_id") or "nosession")
    sid = re.sub(r"[^A-Za-z0-9_-]", "_", sid)[:80]
    spool_dir = os.path.join(_vibemon_dir(), "spool")
    return (
        spool_dir,
        os.path.join(spool_dir, sid + ".jsonl"),
        os.path.join(spool_dir, sid + ".sent"),
    )


def _take_spool(path):
    """Atomically claim a spool file and return its non-blank lines. An
    event appended after the rename starts a fresh spool."""
    claimed = "%s.%d" % (path, os.getpid())
    try:
        os.replace(path, claimed)
    except OSError:
        return []
    try:
        with open(claimed, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except (OSError, UnicodeDecodeError):
        return []
    finally:
        try:
            os.remove(claimed)
        except OSError:
            pass


def _coalesce(event, env, line, now=None):
    """Return the body to POST now, or None when the event was spooled."""
    now = int(time.time()) if now is None else now
    spool_dir, spool, stamp = _spool_paths(env)
    try:
        os.makedirs(spool_dir, exist_ok=True)
    except OSError:
        return line  # can't spool → behave like v30

    if event in COALESCED_EVENTS:
        last = _read_text(stamp, "0")
        last = int(last) if last.isdigit() else 0
        try:
            with open(spool, encoding="utf-8") as f:
                queued = sum(1 for _ in f)
        except (OSError, UnicodeDecodeError):
            queued = 0
        if now - last < COALESCE_WINDOW and queued < COALESCE_MAX:
            try:
                with open(spool, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                return None
            except OSError:
                return line

    try:
        with open(stamp, "w", encoding="utf-8") as f:
            f.write(str(now))
    except OSError:
        pass

    queue = _take_spool(spool)
    if queue:
        return '{"batch":[' + ",".join(queue + [line]) + "]}"
    return line


def _sweep_orphans(env, now=None):
    """Bodies for spools orphaned by agents that died before stop/session_end
    (run on session_start). One body per spool (v32): a spool holds at most
    ~COALESCE_MAX lines, so each body stays under /hook's MAX_BATCH (100);
    merging several spools into one batch could exceed it, and /hook keeps
    only the newest 100 — the oldest events were silently dropped."""
    now = int(time.time()) if now is None else now
    spool_dir = _spool_paths(env)[0]
    try:
        names = os.listdir(spool_dir)
    except OSError:
        return []
    bodies = []
    for name in sorted(names):
        path = os.path.join(spool_dir, name)
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if name.endswith(".jsonl") and age > ORPHAN_SPOOL_SECONDS:
            lines = _take_spool(path)
            if lines:
                bodies.append('{"batch":[' + ",".join(lines) + "]}")
        elif name.endswith(".sent") and age > 7 * 86400:
            try:
                os.remove(path)
            except OSError:
                pass
    return bodies


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


def _fire(event, agent, payload):
    """Build envelope, POST to /hook. Returns 0 on success, 1 on test
    probe failure. For non-test events, returns 0 immediately after
    spawning the detached POST."""
    cwd = os.getcwd()
    ts = _utc_iso()
    project_root = _detect_project_root()
    repo_identifier = project_root if "/" in project_root else ""
    branch = _git(["branch", "--show-current"])
    head_sha = _git(["rev-parse", "HEAD"])

    # Honor user opt-out via ~/.vibemon/config
    cfg = _read_config()
    if cfg.get("no_commit_msg") == "1":
        os.environ["VIBEMON_NO_COMMIT_MSG"] = "1"

    env = build_envelope(
        event, payload, agent, cwd, ts, project_root,
        repo_identifier, branch, head_sha,
    )
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

    to_send = _coalesce(event, env, body.decode("utf-8"))
    if to_send is not None:
        _spawn_post(to_send.encode("utf-8"), api_key, version)
    if event == "session_start":
        for orphan in _sweep_orphans(env):
            _spawn_post(orphan.encode("utf-8"), api_key, version)

    # Gemini CLI requires JSON stdout to allow the hook to proceed.
    if agent == "gemini_cli":
        sys.stdout.write(json.dumps({"decision": "allow"}))

    return 0


# ─── Entry point ────────────────────────────────────────────────────
def main(argv=None):
    argv = argv if argv is not None else sys.argv
    event = argv[1] if len(argv) > 1 else "unknown"
    agent = argv[2] if len(argv) > 2 else "claude_code"

    if event == "__update_check":
        # Internal mode — runs in the detached helper spawned below, with
        # a normal process lifetime so the lock's try/finally is
        # guaranteed. Never builds or sends an envelope.
        _auto_update_once()
        return 0

    if event == "session_start":
        # Non-blocking auto-update check. Invariant #5 applies to the LOCK
        # lifecycle too: the previous daemon thread died abruptly with the
        # parent (hooks return within milliseconds), skipping the
        # finally-rmdir mid-fetch and orphaning update.lock — which
        # permanently disabled auto-update. Run the whole check in a
        # detached process instead; it survives the parent exactly like
        # the POST helper does.
        try:
            _spawn_detached(
                [sys.executable, os.path.abspath(__file__), "__update_check"]
            )
        except Exception:
            pass

    payload = _read_stdin_payload()
    return _fire(event, agent, payload)


if __name__ == "__main__":
    sys.exit(main())
