from __future__ import annotations

import base64
import io

import httpx
import pytest
from conftest import FakeAgent, FakeSandbox, logged_in

from app import uploads as up
from app.agent.service import AgentService
from app.main import app, settings
from app.schemas import AttachmentRef
from app.uploads import (
    UploadRejected,
    build_attachment_note,
    build_image_note,
    check_extension,
    collect_inline_images,
    list_uploads,
    parse_allowed_extensions,
    sanitize_filename,
    save_upload,
    unique_destination,
    validate_echo_path,
)

FILES_ENDPOINT = "/v1/agent/files"
CHAT_ENDPOINT = "/v1/agent/chat/stream"
ALLOWED = frozenset({"txt", "pdf", "md"})


# ---------------------------------------------------------------------------
# units: sanitize_filename / parse_allowed_extensions / check_extension
# ---------------------------------------------------------------------------


def test_sanitize_keeps_cjk_and_maps_spaces():
    assert sanitize_filename("报告 final.pdf") == "报告_final.pdf"


def test_sanitize_neutralizes_traversal():
    out = sanitize_filename("../../etc/passwd.txt")
    assert out == "etc_passwd.txt"
    assert "/" not in out and "\\" not in out
    assert not out.startswith(".")


def test_sanitize_strips_control_chars_and_emoji():
    assert sanitize_filename("a\x00b.txt") == "ab.txt"
    assert sanitize_filename("📄 report.txt") == "report.txt"


def test_sanitize_never_empty():
    assert sanitize_filename(None) == "file"
    assert sanitize_filename("...") == "file"


def test_sanitize_clamps_length_keeping_extension():
    out = sanitize_filename("a" * 150 + ".pdf")
    assert len(out) == up.MAX_NAME_LEN
    assert out.endswith(".pdf")


def test_parse_allowed_extensions():
    assert parse_allowed_extensions("PDF, .Txt ,, md") == {"pdf", "txt", "md"}


def test_check_extension():
    check_extension("a.TXT", ALLOWED)  # case-insensitive, no raise
    with pytest.raises(UploadRejected) as exc:
        check_extension("malware.exe", ALLOWED)
    assert exc.value.status_code == 415
    with pytest.raises(UploadRejected) as exc:
        check_extension("noext", ALLOWED)
    assert "<none>" in exc.value.detail


# ---------------------------------------------------------------------------
# units: _copy_capped / unique_destination / list_uploads / save_upload
# ---------------------------------------------------------------------------


def test_copy_capped_success_is_atomic(tmp_path):
    spool = io.BytesIO(b"x" * 25)
    tmp, dest = tmp_path / ".uploading-1", tmp_path / "final.txt"
    total = up._copy_capped(spool, tmp, dest, max_bytes=100)
    assert total == 25
    assert dest.read_bytes() == b"x" * 25
    assert not tmp.exists()  # os.replace moved it


def test_copy_capped_over_limit_rejects_and_cleans_tmp(tmp_path):
    spool = io.BytesIO(b"x" * 25)
    tmp, dest = tmp_path / ".uploading-1", tmp_path / "final.txt"
    with pytest.raises(UploadRejected) as exc:
        up._copy_capped(spool, tmp, dest, max_bytes=10)
    assert exc.value.status_code == 413
    assert not tmp.exists()
    assert not dest.exists()


def test_unique_destination_suffixes(tmp_path):
    assert unique_destination(tmp_path, "a.txt") == tmp_path / "a.txt"
    (tmp_path / "a.txt").touch()
    assert unique_destination(tmp_path, "a.txt") == tmp_path / "a-1.txt"
    (tmp_path / "a-1.txt").touch()
    assert unique_destination(tmp_path, "a.txt") == tmp_path / "a-2.txt"


def test_list_uploads_skips_hidden_and_dirs(tmp_path):
    directory = up.uploads_dir(tmp_path)
    directory.mkdir()
    (directory / "b.txt").write_bytes(b"12")
    (directory / "a.txt").write_bytes(b"1")
    (directory / ".hidden.txt").write_bytes(b"x")
    (directory / "sub").mkdir()

    files = list_uploads(tmp_path)
    assert [f["name"] for f in files] == ["a.txt", "b.txt"]  # sorted
    assert files[1]["path"] == "uploads/b.txt"
    assert files[1]["size"] == 2
    assert files[1]["container_path"] == "/workspace/uploads/b.txt"
    assert list_uploads(tmp_path / "nonexistent") == []


async def test_save_upload_happy_path(tmp_path):
    info = await save_upload(
        spool=io.BytesIO(b"hello"),
        original_filename="报告 final.pdf",
        workspace=tmp_path,
        max_bytes=100,
        allowed=ALLOWED,
        max_files=10,
    )
    assert info == {
        "name": "报告_final.pdf",
        "path": "uploads/报告_final.pdf",
        "size": 5,
        "container_path": "/workspace/uploads/报告_final.pdf",
    }
    assert (tmp_path / "uploads" / "报告_final.pdf").read_bytes() == b"hello"


async def test_save_upload_bad_extension_creates_nothing(tmp_path):
    with pytest.raises(UploadRejected) as exc:
        await save_upload(
            spool=io.BytesIO(b"MZ"),
            original_filename="malware.exe",
            workspace=tmp_path,
            max_bytes=100,
            allowed=ALLOWED,
            max_files=10,
        )
    assert exc.value.status_code == 415
    assert not up.uploads_dir(tmp_path).exists()


async def test_save_upload_count_cap_409(tmp_path):
    directory = up.uploads_dir(tmp_path)
    directory.mkdir()
    (directory / "a.txt").write_bytes(b"1")
    (directory / "b.txt").write_bytes(b"2")
    with pytest.raises(UploadRejected) as exc:
        await save_upload(
            spool=io.BytesIO(b"3"),
            original_filename="c.txt",
            workspace=tmp_path,
            max_bytes=100,
            allowed=ALLOWED,
            max_files=2,
        )
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# units: validate_echo_path / build_attachment_note
# ---------------------------------------------------------------------------


def test_validate_echo_path(tmp_path):
    ws = tmp_path / "ws"
    directory = up.uploads_dir(ws)
    directory.mkdir(parents=True)
    (directory / "real.txt").write_bytes(b"x")
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"s")
    (directory / "link.txt").symlink_to(outside)

    assert validate_echo_path(ws, "uploads/real.txt") == (directory / "real.txt").resolve()
    assert validate_echo_path(ws, "/workspace/uploads/real.txt") is None  # absolute
    assert validate_echo_path(ws, "uploads/../uploads/real.txt") is None  # ".." part
    assert validate_echo_path(ws, "data/real.txt") is None  # outside uploads/
    assert validate_echo_path(ws, "uploads/missing.txt") is None  # not a file
    assert validate_echo_path(ws, "uploads/link.txt") is None  # symlink escape
    assert validate_echo_path(ws, "") is None
    assert validate_echo_path(ws, "   ") is None


def _ref(path: str, name: str = "x") -> AttachmentRef:
    return AttachmentRef(name=name, path=path)


def test_note_none_when_nothing_valid(tmp_path):
    assert build_attachment_note(tmp_path, []) is None
    assert build_attachment_note(tmp_path, [_ref("uploads/missing.txt")]) is None


def test_note_marks_fresh_and_never_uses_echoed_name(tmp_path):
    directory = up.uploads_dir(tmp_path)
    directory.mkdir()
    (directory / "a.txt").write_bytes(b"hello")
    (directory / "b.txt").write_bytes(b"12")

    note = build_attachment_note(tmp_path, [_ref("uploads/a.txt", name="<script>evil")])
    assert note is not None
    assert note.startswith("[system-injected · attachment manifest]")
    assert "- /workspace/uploads/a.txt (5 B, uploaded this turn)" in note
    assert "- /workspace/uploads/b.txt (2 B)" in note
    assert "evil" not in note and "<script>" not in note  # echoed names never reach prompt
    assert note.count("uploads/a.txt") == 1  # deduped against the scan


def test_note_drops_invalid_echo_but_keeps_scan(tmp_path):
    directory = up.uploads_dir(tmp_path)
    directory.mkdir()
    (directory / "a.txt").write_bytes(b"x")

    note = build_attachment_note(tmp_path, [_ref("../../etc/passwd")])
    assert note is not None
    assert "/etc/passwd" not in note
    assert "- /workspace/uploads/a.txt (1 B)" in note  # scan augmented, not fresh
    assert "uploaded this turn" not in note


def test_note_overflow_line(tmp_path):
    directory = up.uploads_dir(tmp_path)
    directory.mkdir()
    for i in range(65):
        (directory / f"doc{i:02d}.txt").write_bytes(b"x")

    note = build_attachment_note(tmp_path, [_ref("uploads/doc00.txt")])
    assert note is not None
    assert "5 more files not listed" in note
    assert f"ls {up.CONTAINER_UPLOADS}" in note


# ---------------------------------------------------------------------------
# units: collect_inline_images / build_image_note
# ---------------------------------------------------------------------------


def _seed_uploads(tmp_path, files: dict[str, bytes]):
    directory = up.uploads_dir(tmp_path)
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (directory / name).write_bytes(data)


def test_collect_images_first_three_in_echo_order(tmp_path):
    _seed_uploads(
        tmp_path,
        {"notes.txt": b"T", "a.png": b"AA", "b.jpg": b"BB", "c.gif": b"CC", "d.webp": b"DD"},
    )
    refs = [_ref(f"uploads/{n}") for n in ("notes.txt", "a.png", "b.jpg", "c.gif", "d.webp")]

    out = collect_inline_images(tmp_path, refs)
    # txt filtered out, the 4th image is over the cap; order follows the echo
    assert [i["name"] for i in out] == ["a.png", "b.jpg", "c.gif"]
    assert out[0]["data_url"] == "data:image/png;base64," + base64.b64encode(b"AA").decode()
    assert out[1]["data_url"].startswith("data:image/jpeg;base64,")
    assert out[2]["data_url"].startswith("data:image/gif;base64,")


def test_collect_images_skips_invalid_empty_oversize_and_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "MAX_INLINE_IMAGE_BYTES", 4)
    _seed_uploads(tmp_path, {"empty.png": b"", "big.png": b"x" * 5, "ok.png": b"12"})
    refs = [
        _ref("uploads/empty.png"),
        _ref("uploads/big.png"),
        _ref("uploads/missing.png"),
        _ref("../../etc/passwd"),
        _ref("uploads/ok.png"),
        _ref("uploads/ok.png"),  # duplicate echo
    ]

    out = collect_inline_images(tmp_path, refs)
    assert [i["name"] for i in out] == ["ok.png"]


def test_collect_images_empty_workspace_or_refs(tmp_path):
    assert collect_inline_images(tmp_path, []) == []
    assert collect_inline_images(tmp_path / "nonexistent", [_ref("uploads/a.png")]) == []


def test_image_note_uses_inline_count_and_names():
    images = [
        {"name": "a.png", "data_url": "data:image/png;base64,AAA="},
        {"name": "b.webp", "data_url": "data:image/webp;base64,BBB="},
    ]
    note = build_image_note(images)
    assert note.startswith("[system-injected · inline images]")
    assert "2 uploaded image(s) (a.png, b.webp)" in note
    assert "only when the task genuinely needs it" in note  # steers, never forbids tool reads


# ---------------------------------------------------------------------------
# API: POST/GET /v1/agent/files
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    # ASGITransport does not run the lifespan, so wire just enough state.
    app.state.agent_service = AgentService(FakeAgent([]))
    app.state.sandbox = FakeSandbox(workspace_root=tmp_path)
    with logged_in(app, username="tester"):
        transport = httpx.ASGITransport(app=app)
        yield httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _post_file(client, name="notes.txt", content=b"hello", thread_id="t-up", headers=None):
    return client.post(
        FILES_ENDPOINT,
        files={"file": (name, content, "application/octet-stream")},
        data={"thread_id": thread_id},
        headers=headers,
    )


async def test_api_upload_happy_path(client):
    resp = await _post_file(client, name="报告 final.pdf", content=b"PDFDATA")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "报告_final.pdf"  # sanitized name is authoritative
    assert body["path"] == "uploads/报告_final.pdf"
    assert body["size"] == 7
    assert body["container_path"] == "/workspace/uploads/报告_final.pdf"

    workspace = app.state.sandbox.workspace_for("tester", "t-up")
    assert (workspace / "uploads" / "报告_final.pdf").read_bytes() == b"PDFDATA"


async def test_api_upload_collision_gets_suffix(client):
    first = await _post_file(client)
    second = await _post_file(client)
    assert first.json()["name"] == "notes.txt"
    assert second.json()["name"] == "notes-1.txt"


async def test_api_upload_bad_extension_415(client):
    resp = await _post_file(client, name="malware.exe", content=b"MZ")
    assert resp.status_code == 415
    assert ".exe" in resp.json()["detail"]


async def test_api_upload_missing_thread_id_422(client):
    resp = await client.post(
        FILES_ENDPOINT, files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert resp.status_code == 422


async def test_api_upload_requires_session(client):
    app.dependency_overrides.clear()  # exercise the REAL require_user path
    anon = await _post_file(client)
    assert anon.status_code == 401
    assert anon.headers.get("www-authenticate") == "Bearer"

    store = app.state.user_store
    user = await store.create_user("alice", "password123")
    token, _expires = await store.create_session(user.id)
    authed = await _post_file(client, headers={"Authorization": f"Bearer {token}"})
    assert authed.status_code == 200
    # The file lands under alice's two-level namespace, proving per-user dirs
    # end-to-end through the real dependency.
    saved = app.state.sandbox.workspace_for("alice", "t-up") / "uploads" / "notes.txt"
    assert saved.read_bytes() == b"hello"


async def test_api_upload_sandbox_not_ready_503(client):
    app.state.sandbox = None
    resp = await _post_file(client)
    assert resp.status_code == 503


async def test_api_upload_over_limit_413_exact(client, monkeypatch):
    # Body is small enough to pass the middleware (content-length <= max+1MB)
    # so the chunked copy enforces the exact limit.
    monkeypatch.setattr(settings, "upload_max_bytes", 10)
    resp = await _post_file(client, content=b"x" * 15)
    assert resp.status_code == 413
    assert "10-byte" in resp.json()["detail"]
    # No partial file or stray tmp left behind.
    directory = up.uploads_dir(app.state.sandbox.workspace_for("tester", "t-up"))
    assert list_uploads(app.state.sandbox.workspace_for("tester", "t-up")) == []
    assert not any(p.name.startswith(".uploading-") for p in directory.iterdir())


async def test_api_upload_middleware_fast_413(client, monkeypatch):
    monkeypatch.setattr(settings, "upload_max_bytes", 1024)
    resp = await _post_file(client, content=b"x" * (2 * 1024 * 1024))
    assert resp.status_code == 413
    assert resp.json()["detail"] == "upload exceeds size limit"
    assert not up.uploads_dir(app.state.sandbox.workspace_for("tester", "t-up")).exists()


async def test_api_upload_count_cap_409(client, monkeypatch):
    monkeypatch.setattr(settings, "upload_max_files_per_thread", 2)
    assert (await _post_file(client, name="a.txt")).status_code == 200
    assert (await _post_file(client, name="b.txt")).status_code == 200
    third = await _post_file(client, name="c.txt")
    assert third.status_code == 409


async def test_api_list_files(client):
    await _post_file(client, name="b.txt")
    await _post_file(client, name="a.txt")

    resp = await client.get(FILES_ENDPOINT, params={"thread_id": "t-up"})
    assert resp.status_code == 200
    files = resp.json()["files"]
    assert [f["name"] for f in files] == ["a.txt", "b.txt"]
    assert files[0]["container_path"] == "/workspace/uploads/a.txt"

    other = await client.get(FILES_ENDPOINT, params={"thread_id": "other-thread"})
    assert other.json() == {"files": []}

    missing = await client.get(FILES_ENDPOINT)
    assert missing.status_code == 422


async def test_api_list_files_sandbox_not_ready_503(client):
    app.state.sandbox = None
    resp = await client.get(FILES_ENDPOINT, params={"thread_id": "t-up"})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# API: chat/stream attachment manifest integration
# ---------------------------------------------------------------------------


def _wire_agent(fake_events) -> FakeAgent:
    agent = FakeAgent(fake_events)
    app.state.agent_service = AgentService(agent)
    return agent


def _sent_content(agent: FakeAgent) -> str:
    return agent.received_payload["messages"][0]["content"]


async def test_chat_stream_injects_manifest(client, fake_events):
    agent = _wire_agent(fake_events)
    await _post_file(client, name="notes.txt", content=b"data")

    resp = await client.post(
        CHAT_ENDPOINT,
        json={
            "message": "总结",
            "thread_id": "t-up",
            "attachments": [{"name": "notes.txt", "path": "uploads/notes.txt"}],
        },
    )
    assert resp.status_code == 200
    content = _sent_content(agent)
    assert content.startswith("总结\n\n[system-injected · attachment manifest]")
    assert "/workspace/uploads/notes.txt (4 B, uploaded this turn)" in content


async def test_chat_stream_attaches_first_three_images_as_blocks(client, fake_events):
    agent = _wire_agent(fake_events)
    for i, name in enumerate(("a.png", "b.png", "c.png", "d.png")):
        resp = await _post_file(client, name=name, content=f"img{i}".encode())
        assert resp.status_code == 200

    resp = await client.post(
        CHAT_ENDPOINT,
        json={
            "message": "看看这几张图",
            "thread_id": "t-up",
            "attachments": [
                {"name": n, "path": f"uploads/{n}"} for n in ("a.png", "b.png", "c.png", "d.png")
            ],
        },
    )
    assert resp.status_code == 200
    assert agent.received_payload is not None
    content = agent.received_payload["messages"][0]["content"]
    assert isinstance(content, list)
    text_block, *image_blocks = content
    assert text_block["type"] == "text"
    assert text_block["text"].startswith("看看这几张图\n\n[system-injected · attachment manifest]")
    assert "[system-injected · inline images]" in text_block["text"]
    assert "(a.png, b.png, c.png)" in text_block["text"]  # d.png over the cap, not claimed inline
    # Only the first MAX_INLINE_IMAGES echoes become multimodal blocks.
    assert len(image_blocks) == up.MAX_INLINE_IMAGES
    urls = [b["image_url"]["url"] for b in image_blocks]
    assert all(u.startswith("data:image/png;base64,") for u in urls)
    assert urls[0].endswith(base64.b64encode(b"img0").decode())


async def test_chat_stream_text_only_attachment_stays_plain_string(client, fake_events):
    agent = _wire_agent(fake_events)
    await _post_file(client, name="notes.txt", content=b"data")

    resp = await client.post(
        CHAT_ENDPOINT,
        json={
            "message": "总结",
            "thread_id": "t-up",
            "attachments": [{"name": "notes.txt", "path": "uploads/notes.txt"}],
        },
    )
    assert resp.status_code == 200
    assert isinstance(_sent_content(agent), str)  # no images -> old plain-content shape


async def test_chat_stream_drops_invalid_echo_paths(client, fake_events):
    agent = _wire_agent(fake_events)
    resp = await client.post(
        CHAT_ENDPOINT,
        json={
            "message": "总结",
            "thread_id": "t-up",
            "attachments": [
                {"name": "x", "path": "../../etc/passwd"},
                {"name": "y", "path": "uploads/missing.txt"},
            ],
        },
    )
    assert resp.status_code == 200
    assert _sent_content(agent) == "总结"  # nothing valid -> no note at all


async def test_chat_stream_without_attachments_never_injects(client, fake_events):
    agent = _wire_agent(fake_events)
    await _post_file(client, name="notes.txt", content=b"data")

    resp = await client.post(
        CHAT_ENDPOINT, json={"message": "总结", "thread_id": "t-up"}
    )
    assert resp.status_code == 200
    assert _sent_content(agent) == "总结"  # scan-only turns stay silent


async def test_chat_stream_sandbox_none_skips_note(client, fake_events):
    agent = _wire_agent(fake_events)
    app.state.sandbox = None
    resp = await client.post(
        CHAT_ENDPOINT,
        json={
            "message": "总结",
            "thread_id": "t-up",
            "attachments": [{"name": "notes.txt", "path": "uploads/notes.txt"}],
        },
    )
    assert resp.status_code == 200
    assert _sent_content(agent) == "总结"
