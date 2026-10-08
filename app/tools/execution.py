from __future__ import annotations

import json
import posixpath
from pathlib import PurePosixPath

from langchain.tools import tool

from app.context import get_thread_id
from app.sandbox import DockerSandbox


def _result_json(result) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False)


def _normalize_relative_script_path(script_path: str) -> str:
    candidate = script_path.strip()
    if not candidate:
        raise ValueError("script_path must not be empty")

    path = PurePosixPath(candidate)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("script_path must be a relative path inside /workspace")

    normalized = posixpath.normpath(candidate)
    if normalized in {"", "."} or normalized.startswith("../"):
        raise ValueError("script_path must stay inside /workspace")
    return normalized


def build_execution_tools(sandbox: DockerSandbox):
    @tool("bash_exec")
    async def bash_exec(command: str, timeout_seconds: int = 30) -> str:
        """Execute a bash command in the isolated Docker sandbox.

        The sandbox has no network access and cannot see the host filesystem.
        Use this for shell commands, file inspection, compilation, and workspace operations.
        """
        if not command.strip():
            raise ValueError("command must not be empty")

        thread_id = get_thread_id()
        result = await sandbox.run(
            thread_id=thread_id,
            command=command,
            timeout_seconds=timeout_seconds,
        )
        return _result_json(result)

    @tool("python_exec")
    async def python_exec(code: str, timeout_seconds: int = 30) -> str:
        """Execute Python code in the isolated Docker sandbox.

        Use this for calculations, data processing, code experiments, and generating files.
        Python code is provided on stdin, so it does not need shell escaping.
        """
        if not code.strip():
            raise ValueError("code must not be empty")
        if len(code) > 100_000:
            raise ValueError("code is too large; maximum is 100000 characters")

        thread_id = get_thread_id()
        result = await sandbox.run(
            thread_id=thread_id,
            command="python -",
            stdin_data=code,
            timeout_seconds=timeout_seconds,
        )
        return _result_json(result)

    @tool("python_run_script")
    async def python_run_script(
        script_path: str,
        args: list[str] | None = None,
        timeout_seconds: int = 30,
    ) -> str:
        """Run an existing Python script from the current /workspace.

        script_path must be relative to /workspace, for example 'scripts/train.py'.
        """
        normalized_path = _normalize_relative_script_path(script_path)
        cli_args = args or []
        shell_command = "python " + " ".join(
            [
                _shell_quote(normalized_path),
                *(_shell_quote(arg) for arg in cli_args),
            ]
        )

        thread_id = get_thread_id()
        result = await sandbox.run(
            thread_id=thread_id,
            command=shell_command,
            timeout_seconds=timeout_seconds,
        )
        return _result_json(result)

    return [bash_exec, python_exec, python_run_script]


def _shell_quote(value: str) -> str:
    # Avoid an extra dependency just for quoting.
    # This is equivalent to a POSIX single-quote shell quote.
    return "'" + value.replace("'", "'\\''") + "'"
