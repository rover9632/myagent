from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from conftest import FakeStream

from app.sandbox import DockerSandbox


def make_sandbox(tmp_path: Path, **overrides) -> DockerSandbox:
    kwargs = {
        "image": "agent-sandbox:py312",
        "workspace_root": tmp_path,
        "default_timeout_seconds": 30,
        "max_timeout_seconds": 120,
        "memory": "512m",
        "cpus": 1.0,
        "pids_limit": 64,
        "max_output_bytes": 1024,
        "workspace_ttl_days": 7,
    }
    kwargs.update(overrides)
    return DockerSandbox(**kwargs)


def test_map_exit_code():
    assert DockerSandbox._map_exit_code(True, -9) == 124  # timeout wins
    assert DockerSandbox._map_exit_code(False, -9) == 137  # 128 + SIGKILL
    assert DockerSandbox._map_exit_code(False, 1) == 1
    assert DockerSandbox._map_exit_code(False, 0) == 0
    assert DockerSandbox._map_exit_code(False, None) == 124


async def test_read_limited_caps_and_flags(tmp_path):
    sandbox = make_sandbox(tmp_path, max_output_bytes=1024)
    stream = FakeStream([b"x" * 800, b"y" * 500, b"z" * 100])

    text, truncated = await sandbox._read_limited(stream)

    assert len(text) == 1024
    assert truncated is True


async def test_read_limited_under_cap_not_truncated(tmp_path):
    sandbox = make_sandbox(tmp_path, max_output_bytes=1024)
    text, truncated = await sandbox._read_limited(FakeStream([b"short"]))
    assert text == "short"
    assert truncated is False


def _backdate(path: Path, days: float) -> None:
    old = time.time() - days * 86400
    # Touch the inner file too: directory mtime alone would not move on
    # in-place edits, which is what _latest_activity guards against.
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            os.utime(os.path.join(root, name), (old, old))
    os.utime(path, (old, old))


def test_cleanup_removes_only_expired_workspaces(tmp_path):
    sandbox = make_sandbox(tmp_path, workspace_ttl_days=7)

    stale = sandbox.workspace_for("stale-thread")
    (stale / "out.txt").write_text("old")
    _backdate(stale, days=10)

    fresh = sandbox.workspace_for("fresh-thread")
    (fresh / "live.txt").write_text("new")

    removed = sandbox.cleanup_expired_workspaces()

    assert removed == 1
    assert not stale.exists()
    assert fresh.exists()


def test_cleanup_keeps_workspace_with_recent_nested_file(tmp_path):
    sandbox = make_sandbox(tmp_path, workspace_ttl_days=7)

    workspace = sandbox.workspace_for("quiet-dir")
    nested = workspace / "scripts"
    nested.mkdir()
    _backdate(workspace, days=10)
    # Directory tree is old, but one file was just rewritten in place.
    (nested / "train.py").write_text("touch me")

    assert sandbox.cleanup_expired_workspaces() == 0
    assert workspace.exists()


def test_cleanup_disabled_with_zero_ttl(tmp_path):
    sandbox = make_sandbox(tmp_path, workspace_ttl_days=0)
    stale = sandbox.workspace_for("stale-thread")
    _backdate(stale, days=365)

    assert sandbox.cleanup_expired_workspaces() == 0
    assert stale.exists()


def test_safe_thread_id_stable_and_digest_bound():
    a = DockerSandbox._safe_thread_id("demo/1")
    b = DockerSandbox._safe_thread_id("demo_1")
    assert a != b  # digest suffix prevents sanitized-name collisions
    assert a == DockerSandbox._safe_thread_id("demo/1")
    assert "/" not in a and ".." not in a


@pytest.mark.parametrize(
    "raw",
    ["../../etc/passwd", "a" * 300, "中文线程", "!!weird!!"],
)
def test_workspace_stays_under_root(tmp_path, raw):
    sandbox = make_sandbox(tmp_path)
    workspace = sandbox.workspace_for(raw)
    assert workspace.parent == tmp_path.resolve() or tmp_path in workspace.parents
