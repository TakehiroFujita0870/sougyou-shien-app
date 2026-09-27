"""Serve a built Vite dashboard from the loopback control API origin.

Mount this after registering API routes so the dashboard fallback cannot shadow
them. The helper intentionally serves a production ``dist`` build only.
"""
from __future__ import annotations

import ipaddress
from pathlib import Path
from posixpath import normpath

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response


class DashboardBuildMissing(RuntimeError):
    """The built frontend is missing or does not contain a safe entry page."""


_NO_STORE_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def mount_local_dashboard(
    app: FastAPI,
    *,
    dist_dir: str | Path,
    expected_host: str,
    allowed_origin: str,
) -> None:
    """Mount an existing Vite build with strict local request checks.

    Missing builds fail immediately; this never starts or falls back to a Vite
    development server.
    """
    try:
        root = Path(dist_dir).resolve(strict=True)
        index = (root / "index.html").resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise DashboardBuildMissing("Built dashboard files are unavailable") from error
    if not root.is_dir() or not index.is_file() or not _is_within(index, root):
        raise DashboardBuildMissing("Built dashboard files are unavailable")
    if not expected_host or not allowed_origin:
        raise ValueError("expected_host and allowed_origin are required")

    async def serve_index(request: Request) -> Response:
        if not _request_is_allowed(request, expected_host, allowed_origin):
            return Response(status_code=403, headers=_NO_STORE_HEADERS)
        return FileResponse(index, headers=_NO_STORE_HEADERS)

    async def serve_path(request: Request) -> Response:
        if not _request_is_allowed(request, expected_host, allowed_origin):
            return Response(status_code=403, headers=_NO_STORE_HEADERS)

        relative_path = request.path_params.get("path", "")
        if "\\" in relative_path or "\x00" in relative_path:
            return Response(status_code=404, headers=_NO_STORE_HEADERS)
        normalized_path = normpath(relative_path)
        try:
            candidate = (root / normalized_path).resolve(strict=False)
        except (OSError, RuntimeError):
            return Response(status_code=404, headers=_NO_STORE_HEADERS)
        if not _is_within(candidate, root):
            return Response(status_code=404, headers=_NO_STORE_HEADERS)
        if candidate.is_file():
            return FileResponse(candidate, headers=_NO_STORE_HEADERS)

        # Missing asset-like paths must not receive index.html with a 200 status.
        first_segment = normalized_path.split("/", maxsplit=1)[0]
        if Path(normalized_path).suffix or first_segment in {"assets", "api", "v1"}:
            return Response(status_code=404, headers=_NO_STORE_HEADERS)
        return FileResponse(index, headers=_NO_STORE_HEADERS)

    app.add_route("/", serve_index, methods=["GET", "HEAD"], include_in_schema=False)
    app.add_route("/{path:path}", serve_path, methods=["GET", "HEAD"], include_in_schema=False)


def _request_is_allowed(request: Request, expected_host: str, allowed_origin: str) -> bool:
    peer = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(peer).is_loopback:
            return False
    except ValueError:
        return False
    if request.headers.get("host") != expected_host:
        return False
    origin = request.headers.get("origin")
    return origin is None or origin == allowed_origin


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False
