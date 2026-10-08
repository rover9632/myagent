"""Real-docker integration tests for DockerSandbox.run().

These were the gap that let the `docker run -i` bug slip through: every other
test fakes the sandbox. Skipped automatically when docker or the image is
absent so `uv run pytest` stays green on machines without docker.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.sandbox import DockerSandbox


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", "agent-sandbox:py312"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


pytestmark = pytest.mark.skipif(
    not _docker_ready(),
    reason="docker or agent-sandbox:py312 image unavailable",
)


def make_sandbox(tmp_path: Path) -> DockerSandbox:
    return DockerSandbox(
        image="agent-sandbox:py312",
        workspace_root=tmp_path,
        default_timeout_seconds=30,
        max_timeout_seconds=120,
        memory="512m",
        cpus=1.0,
        pids_limit=64,
        max_output_bytes=12000,
    )


async def test_python_exec_stdin_reaches_container(tmp_path):
    # Regression: without `docker run -i`, stdin is dropped at the CLI boundary,
    # `python -` sees instant EOF, executes nothing and exits 0 silently.
    sandbox = make_sandbox(tmp_path)
    result = await sandbox.run(
        thread_id="it-thread",
        command="python -",
        stdin_data="import sys\nprint('STDOUT-OK')\nprint('STDERR-OK', file=sys.stderr)\n",
    )

    assert result.exit_code == 0
    assert "STDOUT-OK" in result.stdout
    assert "STDERR-OK" in result.stderr


async def test_bash_exec_captures_output_and_exit_code(tmp_path):
    sandbox = make_sandbox(tmp_path)
    ok = await sandbox.run(thread_id="it-thread", command="echo hi")
    assert ok.stdout.strip() == "hi"

    fail = await sandbox.run(thread_id="it-thread", command="exit 3")
    assert fail.exit_code == 3


async def test_workspace_files_persist_across_runs(tmp_path):
    sandbox = make_sandbox(tmp_path)
    write = await sandbox.run(
        thread_id="it-thread",
        command="python -",
        stdin_data="open('marker.txt', 'w').write('kept')\n",
    )
    assert write.exit_code == 0

    read = await sandbox.run(thread_id="it-thread", command="cat marker.txt")
    assert read.stdout.strip() == "kept"

    # Different thread must not see another thread's workspace.
    other = await sandbox.run(thread_id="other-thread", command="cat marker.txt")
    assert other.exit_code != 0


async def test_timeout_kills_and_reports_124(tmp_path):
    sandbox = make_sandbox(tmp_path)
    result = await sandbox.run(
        thread_id="it-thread",
        command="sleep 30",
        timeout_seconds=2,
    )
    assert result.timed_out is True
    assert result.exit_code == 124
