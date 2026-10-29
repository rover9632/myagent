"""Render the pages of a workspace PDF to images (agent tool).

Runs in the FastAPI process (not the Docker sandbox) directly on the session
workspace under data/workspaces/. Every rendered image is uploaded to cloud
storage via app.util.cosop and the tool result carries the public URLs —
host paths never reach the user.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pymupdf
from langchain.tools import tool

from app.context import get_thread_id, get_username
from app.sandbox import DockerSandbox
from app.tools.workspace_io import resolve_workspace_path, upload_output_file

MIN_DPI = 50
MAX_DPI = 600
# Each page becomes one uploaded URL inside the model context, so cap the
# per-call page count; longer PDFs must be split first (e.g. via python_exec).
MAX_PAGES = 50


def pdf_to_images(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 200,
    image_format: str = "png",
    max_pages: int = MAX_PAGES,
) -> list[Path]:
    """Render every page of a PDF to an image file; returns the paths in page order.

    Sync and blocking — call through asyncio.to_thread.
    """
    image_format = image_format.lower()
    if image_format == "jpeg":
        image_format = "jpg"
    if image_format not in {"png", "jpg"}:
        raise ValueError("image_format must be one of png, jpg, jpeg")

    output_paths: list[Path] = []
    with pymupdf.open(pdf_path) as doc:
        if doc.page_count > max_pages:
            raise ValueError(
                f"PDF has {doc.page_count} pages, exceeding the {max_pages}-page limit"
            )
        if doc.page_count == 0:
            raise ValueError("PDF has no pages")
        output_dir.mkdir(parents=True, exist_ok=True)
        for page_index, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csRGB)
            output_path = output_dir / f"{pdf_path.stem}_{page_index + 1:03d}.{image_format}"
            if image_format == "jpg":
                pix.save(str(output_path), jpg_quality=90)
            else:
                pix.save(str(output_path))
            output_paths.append(output_path)
    return output_paths


def build_pdf2imgs_tools(sandbox: DockerSandbox):
    @tool("pdf_to_images")
    async def pdf_to_images_tool(
        pdf_path: str,
        output_dir: str = "",
        dpi: int = 200,
        image_format: str = "png",
    ) -> str:
        """Render every page of a PDF in the workspace to PNG or JPG images.

        pdf_path is relative to the session workspace (a leading "/workspace/"
        is accepted), e.g. "uploads/report.pdf". output_dir defaults to
        "<pdf stem>_images" next to the PDF. dpi ranges 50-600 (default 200);
        PDFs longer than 50 pages are rejected. Each image is uploaded to
        cloud storage; the JSON result contains one public URL per page.
        """
        if not MIN_DPI <= dpi <= MAX_DPI:
            raise ValueError(f"dpi must be between {MIN_DPI} and {MAX_DPI}")
        fmt = image_format.lower()
        if fmt not in {"png", "jpg", "jpeg"}:
            raise ValueError("image_format must be one of png, jpg, jpeg")

        username = get_username()
        thread_id = get_thread_id()
        workspace = sandbox.workspace_for(username, thread_id)

        pdf = resolve_workspace_path(workspace, pdf_path)
        if not pdf.is_file():
            raise ValueError(f"PDF file not found: {pdf_path}")
        out_dir = (
            resolve_workspace_path(workspace, output_dir)
            if output_dir.strip()
            else pdf.parent / f"{pdf.stem}_images"
        )

        paths = await asyncio.to_thread(pdf_to_images, pdf, out_dir, dpi, fmt)
        images = []
        for page_number, path in enumerate(paths, start=1):
            url = await upload_output_file(path)
            images.append({"page": page_number, "url": url})
        return json.dumps({"page_count": len(paths), "images": images}, ensure_ascii=False)

    return [pdf_to_images_tool]
