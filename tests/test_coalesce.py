"""Coalescing of the per-tool-call events (v31; orphan sweep split in v32).

bash + activity fire on every tool call and were ~88% of /hook traffic.
A session now sends them at most once per COALESCE_WINDOW; the rest wait
in a per-session spool and ride along with the next send as
{"batch":[…]} (oldest first, the triggering event last). Every other
event goes out immediately. These tests pin both twins: notify.py's
`_coalesce` directly, and the BUILT notify.sh end-to-end with a fake curl.
"""

import json
import os
import re
import stat
import subprocess
import time

import pytest

import notify


# ─── notify.py ──────────────────────────────────────────────────────
@pytest.fixture
def vhome(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


def _line(event, sid="s1", ts="2026-09-29T00:00:00Z"):
    return json.dumps({"v": 2, "event": event, "session_id": sid, "timestamp": ts})


def _send(event, sid="s1", now=1_000_000, ts=None):
    env = {"event": event, "session_id": sid}
    return notify._coalesce(event, env, _line(event, sid, ts or str(now)), now=now)


def test_first_bash_goes_out_immediately(vhome):
    body = _send("bash", now=1_000_000)
    assert json.loads(body)["event"] == "bash"


def test_bash_inside_window_is_spooled_then_rides_with_stop(vhome):
    assert _send("bash", now=1_000_000) is not None
    assert _send("bash", now=1_000_010, ts="b2") is None
    assert _send("activity", now=1_000_020, ts="a3") is None
    body = json.loads(_send("stop", now=1_000_030, ts="s4"))
    assert [e["timestamp"] for e in body["batch"]] == ["b2", "a3", "s4"]
    # spool consumed — the next non-coalesced event is a plain envelope
    assert json.loads(_send("prompt", now=1_000_040))["event"] == "prompt"


def test_bash_past_window_flushes_the_spool(vhome):
    _send("bash", now=1_000_000)
    _send("bash", now=1_000_030, ts="held")
    body = json.loads(_send("bash", now=1_000_000 + notify.COALESCE_WINDOW, ts="late"))
    assert [e["timestamp"] for e in body["batch"]] == ["held", "late"]


def test_spool_cap_forces_a_send(vhome):
    _send("bash", now=1_000_000)
    for i in range(notify.COALESCE_MAX):
        assert _send("bash", now=1_000_001, ts="q%d" % i) is None
    body = json.loads(_send("bash", now=1_000_002, ts="over"))
    assert len(body["batch"]) == notify.COALESCE_MAX + 1


def test_sessions_do_not_share_a_spool(vhome):
    _send("bash", sid="a", now=1_000_000)
    _send("bash", sid="a", now=1_000_001, ts="a-held")
    # session b has never sent → its first bash goes out alone
    assert json.loads(_send("bash", sid="b", now=1_000_002))["event"] == "bash"


def test_session_start_sweeps_each_orphaned_spool_separately(vhome):
    # v32: one body per orphaned spool, so no POST can outgrow /hook's
    # MAX_BATCH (100) — merged, several spools could, and /hook keeps only
    # the newest 100.
    spool_dir = os.path.join(str(vhome), ".vibemon", "spool")
    old = time.time() - notify.ORPHAN_SPOOL_SECONDS - 60
    for sid in ("dead1", "dead2"):
        _send("bash", sid=sid, now=1_000_000)
        _send("bash", sid=sid, now=1_000_001, ts="orphan-" + sid)
        os.utime(os.path.join(spool_dir, sid + ".jsonl"), (old, old))
    now = int(time.time())
    env = {"session_id": "new"}
    body = json.loads(notify._coalesce("session_start", env, _line("session_start", "new", "now"), now=now))
    assert body["event"] == "session_start", "orphans no longer ride with the session_start"
    orphans = [json.loads(b) for b in notify._sweep_orphans(env, now=now)]
    assert [[e["timestamp"] for e in b["batch"]] for b in orphans] == [["orphan-dead1"], ["orphan-dead2"]]
    assert notify._sweep_orphans(env, now=now) == [], "a spool is taken once"


def test_fresh_spools_are_not_swept(vhome):
    _send("bash", sid="live", now=1_000_000)
    _send("bash", sid="live", now=1_000_001, ts="held")
    assert notify._sweep_orphans({"session_id": "new"}, now=int(time.time())) == []


def test_session_id_is_sanitized_into_a_file_name(vhome):
    _send("bash", sid="../../etc/passwd", now=1_000_000)
    spool_dir = os.path.join(str(vhome), ".vibemon", "spool")
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+\.(sent|jsonl)", n) for n in os.listdir(spool_dir))


# ─── BUILT notify.sh, end-to-end ────────────────────────────────────
def _built_notify(dist_dir):
    with open(os.path.join(dist_dir, "install.sh"), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"<< 'NOTIFY_SCRIPT'[^\n]*\n(.*?)\nNOTIFY_SCRIPT", src, re.DOTALL)
    assert m, "NOTIFY_SCRIPT heredoc not found in dist/install.sh"
    return m.group(1)


FAKE_CURL = """#!/usr/bin/env bash
# Records the body of every POST that carries one; ignores the rest.
for a in "$@"; do
  if [ "$a" = "@-" ]; then cat > "$(mktemp "$FAKE_CURL_DIR/body.XXXXXX")"; exit 0; fi
done
prev=""
for a in "$@"; do
  if [ "$prev" = "-d" ]; then printf '%s' "$a" > "$(mktemp "$FAKE_CURL_DIR/body.XXXXXX")"; fi
  prev="$a"
done
exit 0
"""


@pytest.fixture
def sh_env(dist_dir, tmp_path):
    home = tmp_path / "home"
    vdir = home / ".vibemon"
    vdir.mkdir(parents=True)
    (vdir / "api-key").write_text("vbm_test", encoding="utf-8")
    (vdir / "version").write_text("31", encoding="utf-8")
    script = vdir / "notify.sh"
    script.write_text(_built_notify(dist_dir), encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    curl = bindir / "curl"
    curl.write_text(FAKE_CURL, encoding="utf-8")
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    env = dict(os.environ, HOME=str(home), FAKE_CURL_DIR=str(bodies),
               PATH=str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    return script, env, bodies, work, vdir


def _fire_sh(sh_env, event, payload):
    script, env, bodies, work, _ = sh_env
    before = len(os.listdir(bodies))
    r = subprocess.run(["bash", str(script), event, "claude_code"],
                       input=json.dumps(payload), capture_output=True, text=True,
                       env=env, cwd=str(work), timeout=30)
    assert r.returncode == 0, r.stderr
    return before


def _bodies_after(sh_env, before, expect, wait=5.0):
    bodies = sh_env[2]
    deadline = time.time() + wait
    while time.time() < deadline:
        names = sorted(os.listdir(bodies), key=lambda n: os.path.getmtime(os.path.join(bodies, n)))
        if len(names) >= before + expect and all(os.path.getsize(os.path.join(bodies, n)) for n in names):
            break
        time.sleep(0.05)
    time.sleep(0.3)  # a send that should NOT happen gets the same chance to show up
    names = sorted(os.listdir(bodies), key=lambda n: os.path.getmtime(os.path.join(bodies, n)))
    return [json.loads((bodies / n).read_text(encoding="utf-8")) for n in names[before:]]


@pytest.mark.skipif(os.name == "nt", reason="Unix notify.sh; Windows goes through notify.py")
def test_built_notify_sh_coalesces_bash_until_stop(sh_env):
    sid = {"session_id": "sess-1"}
    bash_payload = dict(sid, tool_name="Bash", tool_input={"command": "ls"})

    b = _fire_sh(sh_env, "bash", bash_payload)
    sent = _bodies_after(sh_env, b, 1)
    assert len(sent) == 1 and sent[0]["event"] == "bash"

    b = _fire_sh(sh_env, "bash", bash_payload)
    assert _bodies_after(sh_env, b, 0, wait=0.5) == []
    spool = sh_env[4] / "spool" / "sess-1.jsonl"
    assert len(spool.read_text(encoding="utf-8").splitlines()) == 1

    b = _fire_sh(sh_env, "stop", sid)
    sent = _bodies_after(sh_env, b, 1)
    assert len(sent) == 1
    assert [e["event"] for e in sent[0]["batch"]] == ["bash", "stop"]
    assert not spool.exists()


@pytest.mark.skipif(os.name == "nt", reason="Unix notify.sh; Windows goes through notify.py")
def test_built_notify_sh_sends_each_orphaned_spool_separately(sh_env):
    spool_dir = sh_env[4] / "spool"
    spool_dir.mkdir(exist_ok=True)
    old = time.time() - 15 * 60
    for sid in ("dead1", "dead2"):
        p = spool_dir / (sid + ".jsonl")
        p.write_text(json.dumps({"event": "bash", "timestamp": "orphan-" + sid}) + "\n", encoding="utf-8")
        os.utime(p, (old, old))

    b = _fire_sh(sh_env, "session_start", {"session_id": "new"})
    sent = _bodies_after(sh_env, b, 3)
    assert len(sent) == 3
    plain = [x for x in sent if "batch" not in x]
    batches = sorted([e["timestamp"] for e in x["batch"]] for x in sent if "batch" in x)
    assert len(plain) == 1 and plain[0]["event"] == "session_start"
    assert batches == [["orphan-dead1"], ["orphan-dead2"]]
    assert not list(spool_dir.glob("*.jsonl"))
