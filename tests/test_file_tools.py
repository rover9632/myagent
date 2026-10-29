from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest
from conftest import FakeSandbox
from PIL import Image

from app.context import reset_thread_id, reset_username, set_thread_id, set_username
from app.tools.genpass import CHARSETS, build_genpass_tools
from app.tools.imgs2pdf import build_imgs2pdf_tools
from app.tools.pdf2imgs import MAX_PAGES, build_pdf2imgs_tools
from app.tools.workspace_io import resolve_workspace_path
from app.util import cosop


@pytest.fixture
def bound_context():
    """Bind the ambient username/thread_id exactly like AgentService.stream does."""
    utoken = set_username("alice")
    ttoken = set_thread_id("thread-7")
    try:
        yield
    finally:
        reset_thread_id(ttoken)
        reset_username(utoken)


@pytest.fixture
def sandbox(tmp_path):
    return FakeSandbox(workspace_root=tmp_path / "workspaces")


@pytest.fixture
def fake_cos(monkeypatch):
    """Replace the COS uploader; records (path, suffix) and returns a fake URL."""
    calls: list[tuple[str, str]] = []

    def _upload(x, key=None, prefix="p", suffix=""):
        calls.append((x, suffix))
        return f"https://cos.example.invalid/{Path(x).name}"

    monkeypatch.setattr(cosop, "upload_file", _upload)
    return calls


def _make_images(directory: Path, count: int = 2) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        Image.new("RGB", (8, 8), color=(i * 40, 100, 200)).save(directory / f"page-{i}.png")


def _make_pdf(path: Path, pages: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as doc:
        for _ in range(pages):
            doc.new_page()
        doc.save(path)


# ---------------- resolve_workspace_path ----------------


def test_resolve_workspace_path_rules(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert resolve_workspace_path(ws, "a/b.png") == (ws / "a" / "b.png").resolve()
    # Container-style absolute paths map onto the same host workspace.
    assert resolve_workspace_path(ws, "/workspace/a/b.png") == (ws / "a" / "b.png").resolve()
    assert resolve_workspace_path(ws, "./a") == (ws / "a").resolve()
    for bad in ["", "   ", "/etc/passwd", "../x", "a/../../x"]:
        with pytest.raises(ValueError):
            resolve_workspace_path(ws, bad)


def test_resolve_workspace_path_blocks_symlink_escape(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "link").symlink_to(outside)
    # resolve() follows the symlink, so containment catches the escape.
    with pytest.raises(ValueError):
        resolve_workspace_path(ws, "link/secret.txt")


# ---------------- genpass ----------------


async def test_genpass_returns_requested_passwords():
    (genpass_tool,) = build_genpass_tools()
    raw = await genpass_tool.coroutine(length=24, charset="numeric", count=3)
    passwords = json.loads(raw)["passwords"]
    assert len(passwords) == 3
    assert all(len(pw) == 24 and pw.isdigit() for pw in passwords)

    raw = await genpass_tool.coroutine(length=20, charset="all")
    (password,) = json.loads(raw)["passwords"]
    assert len(password) == 20
    assert all(ch in CHARSETS["all"] for ch in password)


async def test_genpass_rejects_bad_args():
    (genpass_tool,) = build_genpass_tools()
    for kwargs in [
        {"length": 0},
        {"length": 257},
        {"count": 0},
        {"count": 51},
        {"charset": "emoji"},
    ]:
        with pytest.raises(ValueError):
            await genpass_tool.coroutine(**kwargs)


# ---------------- imgs_to_pdf ----------------


async def test_imgs_to_pdf_merges_and_uploads(sandbox, bound_context, fake_cos):
    workspace = sandbox.workspace_for("alice", "thread-7")
    _make_images(workspace / "imgs", count=2)

    (imgs_to_pdf,) = build_imgs2pdf_tools(sandbox)
    raw = await imgs_to_pdf.coroutine(src_dir="imgs", dst="out/merged.pdf")

    payload = json.loads(raw)
    assert payload["images"] == 2
    assert payload["size_bytes"] > 0
    assert payload["url"] == "https://cos.example.invalid/merged.pdf"
    # The real file exists in the workspace and is a valid 2-page PDF.
    merged = workspace / "out" / "merged.pdf"
    assert merged.is_file()
    with pymupdf.open(merged) as doc:
        assert doc.page_count == 2
    # The uploaded artifact is the workspace file, suffix preserved for the URL.
    assert fake_cos == [(str(merged.resolve()), ".pdf")]


async def test_imgs_to_pdf_accepts_container_prefix(sandbox, bound_context, fake_cos):
    workspace = sandbox.workspace_for("alice", "thread-7")
    _make_images(workspace / "imgs", count=1)

    (imgs_to_pdf,) = build_imgs2pdf_tools(sandbox)
    raw = await imgs_to_pdf.coroutine(src_dir="/workspace/imgs", dst="/workspace/merged.pdf")
    assert json.loads(raw)["url"] == "https://cos.example.invalid/merged.pdf"


async def test_imgs_to_pdf_rejects_escapes(sandbox, bound_context, fake_cos):
    workspace = sandbox.workspace_for("alice", "thread-7")
    _make_images(workspace / "imgs", count=1)

    (imgs_to_pdf,) = build_imgs2pdf_tools(sandbox)
    with pytest.raises(ValueError):
        await imgs_to_pdf.coroutine(src_dir="../other", dst="x.pdf")
    with pytest.raises(ValueError):
        await imgs_to_pdf.coroutine(src_dir="/etc", dst="x.pdf")
    with pytest.raises(ValueError):
        await imgs_to_pdf.coroutine(src_dir="imgs", dst="../../evil.pdf")
    assert fake_cos == []  # nothing was merged, so nothing was uploaded


async def test_imgs_to_pdf_rejects_bad_input(sandbox, bound_context, fake_cos):
    workspace = sandbox.workspace_for("alice", "thread-7")
    (workspace / "empty").mkdir()
    (workspace / "bad").mkdir()
    (workspace / "bad" / "notes.txt").write_text("hi")

    (imgs_to_pdf,) = build_imgs2pdf_tools(sandbox)
    with pytest.raises(ValueError, match="not found"):
        await imgs_to_pdf.coroutine(src_dir="nope", dst="x.pdf")
    with pytest.raises(ValueError, match="no image"):
        await imgs_to_pdf.coroutine(src_dir="empty", dst="x.pdf")
    with pytest.raises(ValueError, match="cannot open image"):
        await imgs_to_pdf.coroutine(src_dir="bad", dst="x.pdf")
    with pytest.raises(ValueError, match=r"\.pdf"):
        await imgs_to_pdf.coroutine(src_dir="empty", dst="x.txt")


async def test_imgs_to_pdf_requires_context_binding(sandbox):
    (imgs_to_pdf,) = build_imgs2pdf_tools(sandbox)
    with pytest.raises(RuntimeError, match="username"):
        await imgs_to_pdf.coroutine(src_dir="imgs", dst="x.pdf")


async def test_upload_failure_surfaces_as_tool_error(sandbox, bound_context, monkeypatch):
    workspace = sandbox.workspace_for("alice", "thread-7")
    _make_images(workspace / "imgs", count=1)
    # cosop returns "" on handled failures; the tool must not fall back to paths.
    monkeypatch.setattr(cosop, "upload_file", lambda *a, **k: "")

    (imgs_to_pdf,) = build_imgs2pdf_tools(sandbox)
    with pytest.raises(RuntimeError, match="cloud upload failed"):
        await imgs_to_pdf.coroutine(src_dir="imgs", dst="x.pdf")


# ---------------- pdf_to_images ----------------


async def test_pdf_to_images_renders_and_uploads(sandbox, bound_context, fake_cos):
    workspace = sandbox.workspace_for("alice", "thread-7")
    _make_pdf(workspace / "uploads" / "report.pdf", pages=2)

    (pdf_to_images,) = build_pdf2imgs_tools(sandbox)
    raw = await pdf_to_images.coroutine(pdf_path="uploads/report.pdf", dpi=100)

    payload = json.loads(raw)
    assert payload["page_count"] == 2
    assert [img["url"] for img in payload["images"]] == [
        "https://cos.example.invalid/report_001.png",
        "https://cos.example.invalid/report_002.png",
    ]
    # Default output dir: "<stem>_images" next to the PDF.
    out_dir = workspace / "uploads" / "report_images"
    assert sorted(p.name for p in out_dir.iterdir()) == ["report_001.png", "report_002.png"]
    assert [Path(path).name for path, _ in fake_cos] == ["report_001.png", "report_002.png"]
    assert all(suffix == ".png" for _, suffix in fake_cos)


async def test_pdf_to_images_jpg_and_explicit_output(sandbox, bound_context, fake_cos):
    workspace = sandbox.workspace_for("alice", "thread-7")
    _make_pdf(workspace / "r.pdf", pages=1)

    (pdf_to_images,) = build_pdf2imgs_tools(sandbox)
    raw = await pdf_to_images.coroutine(
        pdf_path="r.pdf", output_dir="pages", image_format="jpeg"
    )

    payload = json.loads(raw)
    assert payload["images"] == [{"page": 1, "url": "https://cos.example.invalid/r_001.jpg"}]
    assert (workspace / "pages" / "r_001.jpg").is_file()
    assert fake_cos[0][1] == ".jpg"  # jpeg normalized to jpg


async def test_pdf_to_images_validation(sandbox, bound_context, fake_cos):
    workspace = sandbox.workspace_for("alice", "thread-7")
    _make_pdf(workspace / "r.pdf", pages=1)

    (pdf_to_images,) = build_pdf2imgs_tools(sandbox)
    with pytest.raises(ValueError, match="dpi"):
        await pdf_to_images.coroutine(pdf_path="r.pdf", dpi=0)
    with pytest.raises(ValueError, match="dpi"):
        await pdf_to_images.coroutine(pdf_path="r.pdf", dpi=1200)
    with pytest.raises(ValueError, match="image_format"):
        await pdf_to_images.coroutine(pdf_path="r.pdf", image_format="gif")
    with pytest.raises(ValueError, match="not found"):
        await pdf_to_images.coroutine(pdf_path="missing.pdf")
    with pytest.raises(ValueError):
        await pdf_to_images.coroutine(pdf_path="/etc/passwd")
    with pytest.raises(ValueError):
        await pdf_to_images.coroutine(pdf_path="r.pdf", output_dir="../out")
    assert fake_cos == []


async def test_pdf_to_images_rejects_oversized_pdfs(sandbox, bound_context, fake_cos):
    workspace = sandbox.workspace_for("alice", "thread-7")
    _make_pdf(workspace / "big.pdf", pages=MAX_PAGES + 1)

    (pdf_to_images,) = build_pdf2imgs_tools(sandbox)
    with pytest.raises(ValueError, match="limit"):
        await pdf_to_images.coroutine(pdf_path="big.pdf")
    assert fake_cos == []
    # No partial output directory is left behind.
    assert not (workspace / "big_images").exists()
