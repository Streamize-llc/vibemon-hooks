"""Auto-update lock lifecycle — stale-lock TTL recovery (v23).

Production evidence (2026-06-06): a lock holder killed before its cleanup
(sleep / SIGKILL / shutdown) left ~/.vibemon/update.lock behind and
silently disabled auto-update FOREVER — one developer machine sat on v18
for six weeks while v19–v22 shipped. These tests pin the recovery
semantics for both runtimes, plus the v23 process model: the check must
run in a detached process, never a daemon thread (a daemon thread dies
with the parent and skips the finally that releases the lock).
"""
import os
import re
import subprocess
import sys
import time

import pytest

import notify


@pytest.fixture
def vd(tmp_path, monkeypatch):
    d = tmp_path / ".vibemon"
    d.mkdir()
    monkeypatch.setattr(notify, "_vibemon_dir", lambda: str(d))
    return d


def _forbid_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network fetch must not happen in this test")
    monkeypatch.setattr(notify.urllib.request, "urlopen", boom)


# ─── notify.py — _auto_update_once lock semantics ────────────────────

def test_fresh_foreign_lock_is_respected(vd, monkeypatch):
    _forbid_network(monkeypatch)
    (vd / "update.lock").mkdir()  # someone else is checking right now
    notify._auto_update_once()
    assert (vd / "update.lock").exists()  # NOT stolen


def test_stale_lock_recovered_and_released(vd, monkeypatch):
    lock = vd / "update.lock"
    lock.mkdir()
    old = time.time() - 7200  # 2 h — well past the 60-min TTL
    os.utime(lock, (old, old))
    # recent last-check → the function returns right after recovery,
    # before any network fetch
    (vd / "last-update-check").write_text(str(int(time.time())))
    _forbid_network(monkeypatch)
    notify._auto_update_once()
    assert not lock.exists()  # recovered, re-acquired, then released


def test_lock_released_after_normal_run(vd, monkeypatch):
    (vd / "last-update-check").write_text(str(int(time.time())))
    _forbid_network(monkeypatch)
    notify._auto_update_once()
    assert not (vd / "update.lock").exists()


# ─── notify.py — process model (invariant #5 for the lock) ───────────

def test_session_start_spawns_detached_helper_not_thread(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        notify, "_spawn_detached",
        lambda cmd, payload=None: calls.setdefault("cmd", cmd),
    )
    monkeypatch.setattr(notify, "_read_stdin_payload", lambda: {})
    monkeypatch.setattr(notify, "_fire", lambda *a: 0)
    rc = notify.main(["notify.py", "session_start", "claude_code"])
    assert rc == 0
    assert calls["cmd"][0] == sys.executable
    assert calls["cmd"][1].endswith("notify.py")
    assert calls["cmd"][2] == "__update_check"


def test_update_check_event_runs_check_and_sends_no_envelope(monkeypatch):
    ran = {}
    monkeypatch.setattr(
        notify, "_auto_update_once", lambda: ran.setdefault("yes", True)
    )

    def no_fire(*a):
        raise AssertionError("__update_check must not build/send an envelope")

    monkeypatch.setattr(notify, "_fire", no_fire)
    rc = notify.main(["notify.py", "__update_check"])
    assert rc == 0
    assert ran.get("yes")


# ─── notify.sh — same TTL semantics, executed for real ───────────────

def _extract_update_fn(dist_dir):
    with open(os.path.join(dist_dir, "install.sh"), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"<< 'NOTIFY_SCRIPT'\n(.*?)\nNOTIFY_SCRIPT", src, re.DOTALL)
    assert m, "NOTIFY_SCRIPT heredoc not found in dist/install.sh"
    fn = re.search(r"(_vibemon_update_check\(\) \{.*?\n  \})", m.group(1), re.DOTALL)
    assert fn, "_vibemon_update_check not found in embedded notify.sh"
    return fn.group(1)


@pytest.mark.skipif(os.name == "nt", reason="bash runtime — Unix artifact")
def test_notify_sh_stale_lock_recovered(dist_dir, tmp_path):
    fn = _extract_update_fn(dist_dir)
    vd = tmp_path / ".vibemon"
    vd.mkdir()
    lock = vd / "update.lock"
    lock.mkdir()
    old = time.time() - 7200
    os.utime(lock, (old, old))
    (vd / "last-update-check").write_text(str(int(time.time())))
    script = 'VIBEMON_DIR="%s"\n%s\n_vibemon_update_check\n' % (vd, fn)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert not lock.exists()  # stale lock recovered, then released by trap


@pytest.mark.skipif(os.name == "nt", reason="bash runtime — Unix artifact")
def test_notify_sh_lock_released_after_run(dist_dir, tmp_path):
    """THE root-cause regression (pre-v23): `local LOCK_DIR` + a
    single-quoted EXIT trap meant the trap expanded $LOCK_DIR AFTER the
    function returned — `rmdir ''` — so the lock was never released and
    auto-update permanently died after its first daily check."""
    fn = _extract_update_fn(dist_dir)
    vd = tmp_path / ".vibemon"
    vd.mkdir()
    (vd / "last-update-check").write_text(str(int(time.time())))
    script = 'VIBEMON_DIR="%s"\n%s\n_vibemon_update_check\n' % (vd, fn)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert not (vd / "update.lock").exists()  # trap actually released it


@pytest.mark.skipif(os.name == "nt", reason="bash runtime — Unix artifact")
def test_notify_sh_fresh_lock_respected(dist_dir, tmp_path):
    fn = _extract_update_fn(dist_dir)
    vd = tmp_path / ".vibemon"
    vd.mkdir()
    (vd / "update.lock").mkdir()  # fresh — concurrent checker
    script = 'VIBEMON_DIR="%s"\n%s\n_vibemon_update_check\n' % (vd, fn)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert (vd / "update.lock").exists()  # NOT stolen
