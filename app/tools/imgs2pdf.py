"""Merge the images of a workspace directory into one PDF (agent tool).

Runs in the FastAPI process (not the Docker sandbox) directly on the session
workspace under data/workspaces/. The generated PDF is uploaded to cloud
storage via app.util.cosop and the tool result carries the public URL —
host paths never reach the user.
"""

from __future__ import annotations

import asyncio
import json
from os import listdir
from pathlib import Path

from langchain.tools import tool
from PIL import Image

from app.context import get_thread_id, get_username
from app.sandbox import DockerSandbox
from app.tools.workspace_io import resolve_workspace_path, upload_output_file


def imgs2pdf(src_dir: Path, dst: Path) -> int:
    """Merge every image in src_dir (sorted by filename, hidden files skipped)
    into a PDF at dst; returns the number of merged images.

    Sync and blocking — call through asyncio.to_thread. Raises ValueError for
    an empty directory or entries PIL cannot open.
    """
    names = [name for name in sorted(listdir(src_dir)) if not name.startswith(".")]
    if not names:
        raise ValueError(f"no image files found in {src_dir.name}/")

    images: list[Image.Image] = []
    try:
        for name in names:
            try:
                images.append(Image.open(src_dir / name).convert("RGB"))
            except Exception as exc:
                raise ValueError(f"cannot open image {name!r}: {exc}") from exc
        dst.parent.mkdir(parents=True, exist_ok=True)
        images[0].save(dst, save_all=True, append_images=images[1:])
    finally:
        for image in images:
            image.close()
    return len(images)


def build_imgs2pdf_tools(sandbox: DockerSandbox):
    @tool("imgs_to_pdf")
    async def imgs_to_pdf(src_dir: str, dst: str = "merged.pdf") -> str:
        """Merge all images in a workspace directory into one PDF, ordered by filename.

        src_dir and dst are relative to the session workspace (a leading
        "/workspace/" is also accepted), e.g. src_dir="uploads/pages" and
        dst="book.pdf". The PDF is uploaded to cloud storage; the JSON result
        contains its public URL, image count and size.
        """
        username = get_username()
        thread_id = get_thread_id()
        workspace = sandbox.workspace_for(username, thread_id)

        src = resolve_workspace_path(workspace, src_dir)
        out = resolve_workspace_path(workspace, dst)
        if not src.is_dir():
            raise ValueError(f"image directory not found: {src_dir}")
        if out.is_dir():
            raise ValueError(f"destination is a directory: {dst}")
        if out.suffix.lower() != ".pdf":
            raise ValueError("dst must end with .pdf")

        count = await asyncio.to_thread(imgs2pdf, src, out)
        url = await upload_output_file(out)
        return json.dumps(
            {"images": count, "size_bytes": out.stat().st_size, "url": url},
            ensure_ascii=False,
        )

    return [imgs_to_pdf]
