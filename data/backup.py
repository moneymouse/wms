import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Backup timestamp is persisted in a plain-text file to avoid any pickle
# dependency.  The file stores a single Unix timestamp float as a string.
# ---------------------------------------------------------------------------

_RECORD_FILE = Path("data/backupRecord.txt")
_INTERVAL = 5 * 24 * 3600  # 5 days in seconds


def _read_last_backup() -> float:
    try:
        return float(_RECORD_FILE.read_text().strip())
    except Exception:
        return 0.0


def _write_last_backup(ts: float):
    _RECORD_FILE.write_text(str(ts))


def backup():
    """Called once at application startup.

    With MySQL the live data is stored in the database server, so file-level
    copying is no longer meaningful.  This function now only enforces the
    5-day interval check and logs the backup event timestamp.  Production
    deployments should configure regular MySQL dumps (e.g. via mysqldump or
    a managed-DB snapshot policy) separately.
    """
    now = time.time()
    last = _read_last_backup()

    if now - last < _INTERVAL:
        return  # not yet due

    _write_last_backup(now)
