from pathlib import Path

from app.sandbox.docker import DockerSandbox


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


def test_workspace_is_stable_and_separated(tmp_path: Path):
    sandbox = make_sandbox(tmp_path)
    a = sandbox.workspace_for("demo/1")
    b = sandbox.workspace_for("demo_1")

    assert a != b
    assert a.exists()
    assert b.exists()
    assert a.parent == tmp_path
    assert b.parent == tmp_path


def test_workspace_stays_under_root(tmp_path: Path):
    sandbox = make_sandbox(tmp_path)
    workspace = sandbox.workspace_for("../../etc/passwd")
    assert workspace.parent == tmp_path
