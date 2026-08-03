"""Automated point-in-time backups of the Balance database.

The whole app is one SQLite file (``data/app.db``); this keeps timestamped
snapshots so a crash or disk-corruption event can't wipe the history. It uses
SQLite's ``VACUUM INTO``, which writes a fully consistent single-file snapshot
(WAL contents included) without blocking the running app.

A daemon thread runs a backup on startup (unless a recent one already exists)
and every ``BALANCE_BACKUP_HOURS`` thereafter -- so it needs no OS scheduler,
no admin rights, and no user to be logged in: it runs whenever the service
runs. Snapshots land in ``data/backups/`` (outside the reload-watched dirs, so
writing them never triggers an app reload).
"""
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime

from sqlmodel import Session, select

from backend.database import DATA_DIR, DB_PATH, RECEIPTS_DIR, engine
from backend.models import AppSettings

BACKUP_DIR = os.path.join(DATA_DIR, "backups")
KEEP = int(os.environ.get("BALANCE_BACKUP_KEEP", "14"))
INTERVAL_HOURS = float(os.environ.get("BALANCE_BACKUP_HOURS", "24"))


def _mirror_target() -> str:
    """The user-configured off-machine backup folder, or '' if unset.

    Read from AppSettings each run so a change on the Settings page takes
    effect without a restart. An env var (BALANCE_BACKUP_MIRROR) overrides it.
    """
    env = os.environ.get("BALANCE_BACKUP_MIRROR")
    if env:
        return env
    try:
        with Session(engine) as session:
            s = session.exec(select(AppSettings)).first()
            return (s.backup_mirror_path or "").strip() if s else ""
    except Exception:
        return ""


def _snapshots(directory: str) -> list:
    if not os.path.isdir(directory):
        return []
    return sorted(f for f in os.listdir(directory)
                  if f.startswith("app-") and f.endswith(".db"))


def _newest_backup_mtime():
    snaps = [os.path.join(BACKUP_DIR, f) for f in _snapshots(BACKUP_DIR)]
    return max((os.path.getmtime(p) for p in snaps), default=None)


def run_backup() -> str:
    """Write one consistent snapshot of app.db locally, prune, mirror receipts,
    and (if configured) copy the whole set to an off-machine folder too."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"app-{ts}.db")
    conn = sqlite3.connect(DB_PATH)
    try:
        # VACUUM INTO writes a consistent snapshot even while the app is writing
        # and even in WAL mode -- unlike a raw file copy, which can miss the -wal.
        conn.execute("VACUUM INTO ?", (dest,))
    finally:
        conn.close()
    _prune(BACKUP_DIR)
    mirrored = _mirror_receipts(BACKUP_DIR)
    print(f"[backup] {dest} ({os.path.getsize(dest)} bytes); "
          f"receipts mirrored: {mirrored}; keeping last {KEEP}")
    _mirror_offsite(dest)
    return dest


def _mirror_offsite(local_snapshot: str) -> None:
    """Copy the fresh snapshot + receipts to the user's off-machine folder.

    Best-effort: if the target is unset or unreachable (drive unplugged, sync
    folder missing) we log and carry on -- the local backup still succeeded.
    """
    target = _mirror_target()
    if not target:
        return
    try:
        os.makedirs(target, exist_ok=True)
        shutil.copy2(local_snapshot, os.path.join(target, os.path.basename(local_snapshot)))
        _prune(target)
        mirrored = _mirror_receipts(target)
        print(f"[backup] off-site copy -> {target} (receipts: {mirrored})")
    except Exception as exc:
        print(f"[backup] off-site mirror to '{target}' failed: {exc}")


def _prune(directory: str) -> None:
    if KEEP <= 0:
        return
    snaps = _snapshots(directory)
    for old in snaps[:-KEEP]:
        try:
            os.remove(os.path.join(directory, old))
        except OSError:
            pass


def _mirror_receipts(base_dir: str) -> int:
    """Copy new/updated receipt images into base_dir/receipts (cheap mirror)."""
    if not os.path.isdir(RECEIPTS_DIR):
        return 0
    dest = os.path.join(base_dir, "receipts")
    os.makedirs(dest, exist_ok=True)
    copied = 0
    for name in os.listdir(RECEIPTS_DIR):
        src = os.path.join(RECEIPTS_DIR, name)
        dst = os.path.join(dest, name)
        if os.path.isfile(src) and (not os.path.exists(dst)
                                    or os.path.getmtime(src) > os.path.getmtime(dst)):
            shutil.copy2(src, dst)
            copied += 1
    return copied


def _loop() -> None:
    while True:
        try:
            newest = _newest_backup_mtime()
            age_h = None if newest is None else (time.time() - newest) / 3600
            if age_h is None or age_h >= INTERVAL_HOURS:
                run_backup()
        except Exception as exc:  # never let the backup thread die
            print(f"[backup] error: {exc}")
        # Re-check hourly; the age guard means frequent restarts (e.g. reloads)
        # don't produce a snapshot each time -- only when one is actually due.
        time.sleep(3600)


def start_scheduler() -> None:
    """Start the background backup thread. Safe to call once per process."""
    threading.Thread(target=_loop, daemon=True, name="balance-backup").start()
