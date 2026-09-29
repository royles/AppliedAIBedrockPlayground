"""Serve the built React app from FastAPI (used on Cloudera AI without npm)."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
ASSETS_DIR = FRONTEND_DIST / "assets"
INDEX_HTML = FRONTEND_DIST / "index.html"

NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


class AssetStaticFiles(StaticFiles):
    """Static files with cache-friendly headers and permissive CORS for crossorigin links."""

    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
            response.headers.setdefault("Access-Control-Allow-Origin", "*")
        return response


def mount_frontend(app: FastAPI) -> bool:
    """Mount frontend/dist if present. Returns True when mounted."""
    if not INDEX_HTML.exists():
        return False

    if ASSETS_DIR.is_dir():
        app.mount(
            "/assets",
            AssetStaticFiles(directory=str(ASSETS_DIR)),
            name="frontend-assets",
        )

    @app.get("/", include_in_schema=False)
    async def serve_index() -> FileResponse:
        return FileResponse(INDEX_HTML, headers=NO_CACHE_HEADERS)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        if full_path.startswith("api") or full_path in {"docs", "openapi.json", "redoc"}:
            raise HTTPException(status_code=404)
        asset = FRONTEND_DIST / full_path
        if asset.is_file():
            headers = None
            if full_path == "index.html":
                headers = NO_CACHE_HEADERS
            return FileResponse(asset, headers=headers)
        return FileResponse(INDEX_HTML, headers=NO_CACHE_HEADERS)

    return True
