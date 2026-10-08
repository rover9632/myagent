from __future__ import annotations

import json

import pytest
from conftest import FakeSandbox

from app.context import reset_thread_id, set_thread_id
from app.tools.execution import _normalize_relative_script_path, _shell_quote, build_execution_tools


def test_rejects_absolute_and_traversing_paths():
    # Any literal ".." segment is rejected, even "scripts/../data" which would
    # resolve back inside the workspace: strict-whitelist style.
    bad_paths = [
        "",
        "   ",
        "/etc/passwd",
        "../run.py",
        "scripts/../../escape.py",
        "scripts/../x.py",
    ]
    for bad in bad_paths:
        with pytest.raises(ValueError):
            _normalize_relative_script_path(bad)


def test_normalizes_inside_workspace():
    assert _normalize_relative_script_path("./run.py") == "run.py"
    assert _normalize_relative_script_path("scripts//train.py") == "scripts/train.py"


def test_shell_quote_roundtrip():
    assert _shell_quote("simple") == "'simple'"
    # Embedded single quotes must be re-opened POSIX-style.
    assert _shell_quote("it's") == "'it'\\''s'"


async def test_bash_exec_json_contract_and_thread_binding():
    sandbox = FakeSandbox()
    token = set_thread_id("thread-7")
    try:
        bash_exec, _python_exec, _run_script = build_execution_tools(sandbox)
        raw = await bash_exec.coroutine(command="ls", timeout_seconds=5)
    finally:
        reset_thread_id(token)

    payload = json.loads(raw)
    assert payload["exit_code"] == 0
    assert set(payload) == {
        "exit_code",
        "stdout",
        "stderr",
        "duration_ms",
        "timed_out",
        "output_truncated",
    }
    # The tool must forward the ambient thread_id, never a client-supplied one.
    assert sandbox.calls[0]["thread_id"] == "thread-7"
    assert sandbox.calls[0]["command"] == "ls"


async def test_python_exec_feeds_code_via_stdin():
    sandbox = FakeSandbox()
    token = set_thread_id("thread-7")
    try:
        _bash, python_exec, _run = build_execution_tools(sandbox)
        await python_exec.coroutine(code="print(1)", timeout_seconds=3)
    finally:
        reset_thread_id(token)

    assert sandbox.calls[0]["command"] == "python -"
    assert sandbox.calls[0]["stdin_data"] == "print(1)"


async def test_python_exec_rejects_oversized_code():
    _bash, python_exec, _run = build_execution_tools(FakeSandbox())
    with pytest.raises(ValueError):
        await python_exec.coroutine(code="x" * 100_001, timeout_seconds=3)


async def test_python_run_script_quotes_arguments():
    sandbox = FakeSandbox()
    token = set_thread_id("thread-7")
    try:
        _bash, _python, run_script = build_execution_tools(sandbox)
        await run_script.coroutine(script_path="a b.py", args=["it's me"], timeout_seconds=3)
    finally:
        reset_thread_id(token)

    # Full command: `python <quoted path> <quoted args...>`
    assert sandbox.calls[0]["command"] == "python 'a b.py' 'it'\\''s me'"
