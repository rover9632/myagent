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
    a = sandbox.workspace_for("alice", "demo/1")
    b = sandbox.workspace_for("alice", "demo_1")
    c = sandbox.workspace_for("bob", "demo/1")

    assert a != b  # digest suffix separates sanitized-collision thread ids
    assert a != c  # same thread id under different users never collides
    assert a.exists()
    assert b.exists()
    assert c.exists()
    assert a.parent.parent == tmp_path  # exactly two levels: root/<user>/<thread>
    assert b.parent == a.parent  # same user dir
    assert c.parent != a.parent  # different user dir


def test_workspace_stays_under_root(tmp_path: Path):
    sandbox = make_sandbox(tmp_path)
    workspace = sandbox.workspace_for("alice", "../../etc/passwd")
    assert workspace.parent.parent == tmp_path
    # Even a hostile *username* stays exactly two levels under the root.
    evil = sandbox.workspace_for("../../evil", "t")
    assert evil.parent.parent == tmp_path
