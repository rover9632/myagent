"""Shared workspace + cloud-upload plumbing for the host-side file tools.

Unlike the execution tools (which run inside Docker), genpass/imgs2pdf/pdf2imgs
run in the FastAPI process and operate directly on the same host directory the
container sees as /workspace (data/workspaces/<user>/<thread>). Two invariants
are shared by all of them:

- Path arguments are workspace-relative and can never escape: same strict
  rules as execution.py's _normalize_relative_script_path (no absolute paths,
  no ".." segments), plus a resolve() containment check so even a symlink
  planted inside the workspace cannot point out of it.
- Generated files reach the user as cloud URLs, never as host paths: outputs
  are uploaded with app.util.cosop.upload_file and the returned URL replaces
  the file in the tool result.
"""

from __future__ import annotations

import asyncio
import logging
import posixpath
from pathlib import Path, PurePosixPath

from app.util import cosop

logger = logging.getLogger(__name__)

# The model knows the sandbox layout, so "/workspace/x" is accepted and mapped
# onto the same host directory; every other absolute path is rejected.
_CONTAINER_PREFIX = "/workspace/"


def resolve_workspace_path(workspace: Path, raw: str) -> Path:
    """Map a tool path argument onto a host path strictly inside the workspace.

    The target need not exist (output paths use this too). Raises ValueError
    for empty/absolute/escaping paths.
    """
    candidate = (raw or "").strip()
    if not candidate:
        raise ValueError("path must not be empty")
    if candidate.startswith(_CONTAINER_PREFIX):
        candidate = candidate[len(_CONTAINER_PREFIX) :]
    elif candidate.startswith("/"):
        raise ValueError(f"path must be relative to the workspace root: {raw!r}")

    path = PurePosixPath(candidate)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"path must stay inside the workspace: {raw!r}")

    normalized = posixpath.normpath(candidate)
    if normalized in {"", "."}:
        return workspace.resolve()
    if normalized.startswith("../"):
        raise ValueError(f"path must stay inside the workspace: {raw!r}")

    resolved = (workspace / normalized).resolve()
    if not resolved.is_relative_to(workspace.resolve()):
        raise ValueError(f"path escapes the workspace: {raw!r}")
    return resolved


async def upload_output_file(path: Path) -> str:
    """Upload a generated file to COS and return its public URL.

    cosop.upload_file returns "" on handled failures and may raise on others
    (e.g. unconfigured credentials); both collapse into a RuntimeError so the
    model sees a clean tool error instead of a stack trace — and a host path
    never leaks to the user as a fallback.
    """
    try:
        url = await asyncio.to_thread(cosop.upload_file, str(path), suffix=path.suffix.lower())
    except Exception:
        logger.exception("COS upload raised for %s", path)
        url = ""
    if not url:
        raise RuntimeError(f"cloud upload failed for {path.name}")
    return url
