"""Loopback-only history WebUI.

This v1 intentionally has no authentication because it refuses non-loopback binds
and rejects requests not originating from 127.0.0.1 or ::1.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from dictate.config import Config
from dictate.logging_setup import get_logger
from dictate.webui.routes import create_router
from dictate.webui.store import HistoryStore

log = get_logger(__name__)
LOOPBACK_CLIENTS = {"127.0.0.1", "::1"}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; script-src 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class LoopbackOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        client = request.client.host if request.client else ""
        if client not in LOOPBACK_CLIENTS:
            response = PlainTextResponse("Forbidden", status_code=403)
        else:
            response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="dictate history", docs_url=None, redoc_url=None)
    base_dir = Path(__file__).parent
    store = HistoryStore(config)
    app.state.config = config
    app.state.history_store = store
    app.add_middleware(LoopbackOnlyMiddleware)
    app.mount("/static", StaticFiles(directory=base_dir / "static"), name="static")
    app.include_router(create_router(store, base_dir / "templates", config))
    return app


def run(config: Config, host: str = "127.0.0.1", port: int = 47843) -> None:
    if not _is_loopback_host(host):
        raise ValueError("dictate WebUI refuses non-loopback hosts")
    log.info("starting history WebUI on http://%s:%s", host, port)
    uvicorn.run(create_app(config), host=host, port=port)


def start_in_background(config: Config, host: str = "127.0.0.1", port: int = 47843):
    """Start uvicorn in a daemon thread. Returns the thread."""
    import threading

    if not _is_loopback_host(host):
        raise ValueError("dictate WebUI refuses non-loopback hosts")

    def _serve() -> None:
        try:
            log.info("starting background history WebUI on http://%s:%s", host, port)
            uv_config = uvicorn.Config(
                create_app(config), host=host, port=port, log_level="warning", access_log=False
            )
            uvicorn.Server(uv_config).run()
        except Exception:  # noqa: BLE001
            log.exception("WebUI background server crashed")

    thread = threading.Thread(target=_serve, name="dictate-webui", daemon=True)
    thread.start()
    return thread


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
