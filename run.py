"""
Single entrypoint: runs the FastAPI backend (JSON API) and the NiceGUI
frontend (web UI) in one process, on one port.

Usage:
    python run.py

Then open http://<this-machine-ip>:8000 from any browser on your
Tailscale network (desktop or phone).
"""
import os

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from nicegui import ui

from backend.main import app  # FastAPI app with API routers already attached
from backend.database import RECEIPTS_DIR
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

ui.run_with(app, title="Balance", favicon="/icon-assets/icon.png", storage_secret=_STORAGE_SECRET)

if __name__ == "__main__":
    import uvicorn

    # Port and auto-reload are env-configurable so one entrypoint serves both the
    # production service (defaults: :8000, no reload) and a live-reload run
    # (BALANCE_RELOAD=1). Reload watches ONLY the source dirs -- never data/ --
    # so the app's constant writes to app.db can't trigger a restart loop.
    _port = int(os.environ.get("BALANCE_PORT", "8000"))
    if os.environ.get("BALANCE_RELOAD") == "1":
        uvicorn.run("run:app", host="0.0.0.0", port=_port, reload=True,
                    reload_dirs=[os.path.join(_HERE, "backend"),
                                 os.path.join(_HERE, "frontend")])
    else:
        uvicorn.run(app, host="0.0.0.0", port=_port)
