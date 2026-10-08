from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_THREAD_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(slots=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    output_truncated: bool = False

    def to_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "output_truncated": self.output_truncated,
        }


class DockerSandbox:
    """Run untrusted shell/Python workloads in a heavily restricted Docker container.

    The FastAPI process itself remains on the host. Only the workload enters Docker.
    The workspace is the only host directory mounted into the container.
    """

    def __init__(
        self,
        *,
        image: str,
        workspace_root: Path,
        default_timeout_seconds: int,
        max_timeout_seconds: int,
        memory: str,
        cpus: float,
        pids_limit: int,
        max_output_bytes: int,
        workspace_ttl_days: int = 7,
        docker_binary: str = "docker",
    ) -> None:
        self.image = image
        self.workspace_root = workspace_root
        self.default_timeout_seconds = default_timeout_seconds
        self.max_timeout_seconds = max_timeout_seconds
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.max_output_bytes = max_output_bytes
        self.workspace_ttl_days = workspace_ttl_days
        self.docker_binary = docker_binary

        self.workspace_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_thread_id(thread_id: str) -> str:
        value = _THREAD_ID_RE.sub("_", thread_id).strip("._-")
        value = value[:64] or "default"
        digest = hashlib.sha256(thread_id.encode()).hexdigest()[:12]
        return f"{value}-{digest}"

    def workspace_for(self, thread_id: str) -> Path:
        path = self.workspace_root / self._safe_thread_id(thread_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def check_available(self) -> None:
        """Fail fast when Docker or the sandbox image is unavailable."""
        proc = await asyncio.create_subprocess_exec(
            self.docker_binary,
            "info",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            message = (
                stderr.decode(errors="replace").strip()
                or stdout.decode(errors="replace").strip()
            )
            raise RuntimeError(f"Docker is not available: {message}")

        proc = await asyncio.create_subprocess_exec(
            self.docker_binary,
            "image",
            "inspect",
            self.image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Sandbox image '{self.image}' was not found. "
                f"Build it first with the README command. {stderr.decode(errors='replace').strip()}"
            )

    async def run(
        self,
        *,
        thread_id: str,
        command: str,
        stdin_data: str | None = None,
        timeout_seconds: int | None = None,
    ) -> SandboxResult:
        timeout = timeout_seconds or self.default_timeout_seconds
        timeout = max(1, min(timeout, self.max_timeout_seconds))

        workspace = self.workspace_for(thread_id)
        container_name = f"agent-sbx-{uuid.uuid4().hex[:12]}"

        # The sandbox intentionally has no network and no host filesystem access.
        docker_args = [
            self.docker_binary,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.pids_limit),
            "--memory",
            self.memory,
            "--cpus",
            str(self.cpus),
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=64m",
            "--tmpfs",
            "/run:rw,nosuid,nodev,noexec,size=16m",
            "-e",
            "HOME=/tmp",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-v",
            f"{workspace}:/workspace:rw",
            "-w",
            "/workspace",
            "--user",
            "1000:1000",
            self.image,
            "/bin/bash",
            "-lc",
            command,
        ]

        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *docker_args,
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_task = asyncio.create_task(self._read_limited(proc.stdout))
        stderr_task = asyncio.create_task(self._read_limited(proc.stderr))
        timed_out = False

        # Feed stdin before waiting for the child. `python -` otherwise waits
        # forever for EOF and the sandbox would hit its timeout.
        if stdin_data is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_data.encode())
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            try:
                proc.stdin.close()
                await proc.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except TimeoutError:
            timed_out = True
            proc.kill()
            await proc.wait()
            # Killing the docker CLI does not guarantee the container itself has
            # stopped, so explicitly remove it on timeout.
            await self._force_remove_container(container_name)

        stdout, stdout_truncated = await stdout_task
        stderr, stderr_truncated = await stderr_task

        duration_ms = int((time.monotonic() - started) * 1000)
        return SandboxResult(
            exit_code=self._map_exit_code(timed_out, proc.returncode),
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=timed_out,
            output_truncated=stdout_truncated or stderr_truncated,
        )

    @staticmethod
    def _map_exit_code(timed_out: bool, returncode: int | None) -> int:
        if timed_out:
            return 124
        if returncode is None:
            return 124  # defensive: process never finished
        if returncode < 0:
            # Shell convention for signal death (docker CLI killed by SIGKILL -> 137).
            return 128 - returncode
        return returncode

    def cleanup_expired_workspaces(self, ttl_days: int | None = None) -> int:
        """Delete thread workspaces untouched for longer than the TTL.

        Returns the number of removed directories. Only immediate subdirectories
        of workspace_root are considered; the root itself is never removed.
        A TTL of 0 disables cleanup.
        """
        days = self.workspace_ttl_days if ttl_days is None else ttl_days
        if days <= 0:
            return 0

        cutoff = time.time() - days * 86400
        removed = 0
        for entry in self.workspace_root.iterdir():
            if not entry.is_dir():
                continue
            try:
                if self._latest_activity(entry) >= cutoff:
                    continue
                shutil.rmtree(entry)
                removed += 1
            except OSError:
                # Directory vanished or is mid-write by another thread; retry next cycle.
                continue
        return removed

    @staticmethod
    def _latest_activity(directory: Path) -> float:
        # A directory's own mtime only moves on create/delete of direct children,
        # so modifying a file inside would look "stale". Walk the subtree instead;
        # workspaces are small and this runs hourly.
        latest = directory.stat().st_mtime
        for root, dirs, files in os.walk(directory):
            for name in dirs + files:
                try:
                    mtime = os.stat(os.path.join(root, name)).st_mtime
                except OSError:
                    continue
                latest = max(latest, mtime)
        return latest

    async def _force_remove_container(self, container_name: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            self.docker_binary,
            "rm",
            "-f",
            container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
            await proc.wait()

    async def _read_limited(self, stream) -> tuple[str, bool]:
        chunks: list[bytes] = []
        total = 0
        truncated = False

        while True:
            chunk = await stream.read(8192)
            if not chunk:
                break
            if total < self.max_output_bytes:
                remaining = self.max_output_bytes - total
                kept = chunk[:remaining]
                chunks.append(kept)
                total += len(kept)
                if len(chunk) > remaining:
                    truncated = True
            else:
                truncated = True

        text = b"".join(chunks).decode(errors="replace")
        return text, truncated
