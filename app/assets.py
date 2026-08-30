from hashlib import sha256
from pathlib import Path

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class CachedStaticFiles(StaticFiles):
    """Serve versioned static assets with explicit browser and CDN caching."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code in {200, 304}:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response


def asset_version(*paths: Path) -> str:
    """Return a short content hash used to invalidate immutable asset URLs."""
    digest = sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]
