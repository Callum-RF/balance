"""
Single entrypoint: runs the FastAPI backend (JSON API) and the NiceGUI
frontend (web UI) in one process, on one port.

Usage:
    python run.py

Then open http://localhost:8000 (API docs at /docs). The server listens on
localhost by default; for remote access, front it with Tailscale rather than
exposing it directly (see BALANCE_HOST and DEPLOY.md).
"""
import os

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from nicegui import ui

from backend.main import app  # FastAPI app with API routers already attached
from backend.database import RECEIPTS_DIR
from backend.deploy import PREFIX
import frontend.ui  # noqa: F401  (registers @ui.page routes as a side effect)

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_HERE, "frontend", "static")

# Mount static assets directly on the FastAPI app we actually serve. (NiceGUI's
# app.add_static_files registers on nicegui.app, a *different* instance from
# backend.main.app, so those mounts never reached the running server -- which
# is why /icon-assets/* and the PWA manifest used to 404.) Absolute paths keep
# this independent of the process's working directory.
app.mount("/icon-assets", StaticFiles(directory=_STATIC_DIR), name="icon-assets")
app.mount("/receipt-images", StaticFiles(directory=RECEIPTS_DIR), name="receipt-images")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Served from the site root so the service worker's scope is "/" (a worker
    # under /icon-assets/ could only control that sub-path). No-cache so an
    # updated worker is always picked up rather than served stale.
    return FileResponse(os.path.join(_STATIC_DIR, "sw.js"), media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

# storage_secret enables per-browser session storage (app.storage.user),
# which the optional PIN lock uses to remember an unlocked session. The
# secret signs the session cookie; persist one per install so sessions
# survive restarts.
_SECRET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", ".storage-secret")
if os.path.exists(_SECRET_FILE):
    with open(_SECRET_FILE) as f:
        _STORAGE_SECRET = f.read().strip()
else:
    import secrets as _secrets
    _STORAGE_SECRET = _secrets.token_hex(32)
    with open(_SECRET_FILE, "w") as f:
        f.write(_STORAGE_SECRET)

# The session cookie gets its own name. Every Ensemble app shares one address,
# and cookies there are shared too: with the default name each app would keep
# overwriting the others' session, which for Balance means the PIN lock asking
# again after every visit to another app.
ui.run_with(app, title="Balance", favicon="/icon-assets/icon.png", storage_secret=_STORAGE_SECRET,
            session_middleware_kwargs={"session_cookie": "balance_session"})


class UnderPrefix:
    """Serve the app as if it lived at a prefix on a shared address.

    Setting root_path is what makes every link the app writes start with the
    prefix (NiceGUI reads it for its own files, page links and live connection).
    The path has to *include* the prefix too — that is the ASGI convention, and
    without it pages load while every framework file 404s.

    Requests arrive in two shapes and both are accepted:
      /stats            Tailscale's path proxy strips the prefix before forwarding
      /balance/stats    a browser pointed straight at this port, or the old
                        port address, sends it whole
    so the prefix is put back when it is missing and left alone when present.
    """

    def __init__(self, inner, prefix: str):
        self.inner, self.prefix = inner, prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            scope = dict(scope, root_path=self.prefix)
            if not (path == self.prefix or path.startswith(self.prefix + "/")):
                scope["path"] = self.prefix + path
                scope["raw_path"] = scope["path"].encode()
        await self.inner(scope, receive, send)


# What uvicorn serves. `app` stays the plain FastAPI app, which is what the
# tests import.
asgi = UnderPrefix(app, PREFIX) if PREFIX else app

if __name__ == "__main__":
    import uvicorn

    # Port and auto-reload are env-configurable so one entrypoint serves both the
    # production service (defaults: :8000, no reload) and a live-reload run
    # (BALANCE_RELOAD=1). Reload watches ONLY the source dirs -- never data/ --
    # so the app's constant writes to app.db can't trigger a restart loop.
    _port = int(os.environ.get("BALANCE_PORT", "8000"))
    # Localhost only. Tailscale proxies to 127.0.0.1, so binding every interface
    # would add nothing except reachability from the local network, where
    # nothing authenticates in front of this API. Override for a deliberate LAN
    # run: BALANCE_HOST=0.0.0.0
    _host = os.environ.get("BALANCE_HOST", "127.0.0.1")
    if os.environ.get("BALANCE_RELOAD") == "1":
        uvicorn.run("run:asgi", host=_host, port=_port, reload=True,
                    reload_dirs=[os.path.join(_HERE, "backend"),
                                 os.path.join(_HERE, "frontend")])
    else:
        uvicorn.run(asgi, host=_host, port=_port)
