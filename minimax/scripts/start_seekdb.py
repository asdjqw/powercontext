"""Start a local seekdb server for the demo, if one is not already running.

The evaluator may instead point SEEKDB_DSN at an existing seekdb/OceanBase
MySQL endpoint; in that case this script exits immediately.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pymysql

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / ".seekdb"
PID_FILE = BASE / "seekdb.pid"


def _dsn() -> str:
    return os.environ.get("SEEKDB_DSN", "mysql://root@127.0.0.1:2881/sdd_context")


def _alive() -> bool:
    parsed = urlparse(_dsn())
    try:
        conn = pymysql.connect(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 2881,
            user=parsed.username or "root",
            password=parsed.password or "",
            connect_timeout=2,
        )
        conn.close()
        return True
    except Exception:
        return False


def _candidate_binary() -> Path | None:
    configured = os.environ.get("SEEKDB_BIN")
    if configured and Path(configured).is_file():
        return Path(configured)
    for name in ("seekdb", "seekdb.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    try:
        import pylibseekdb

        package_dir = Path(pylibseekdb.__file__).parent
        for candidate in (
            package_dir.parent / "pylibseekdb.libs" / "seekdb.exe",
            package_dir.parent / "pylibseekdb.libs" / "seekdb",
            package_dir / "seekdb.exe",
        ):
            if candidate.is_file():
                return candidate
    except Exception:
        pass
    return None


def main() -> int:
    if _alive():
        print(f"seekdb already reachable: {_dsn()}")
        return 0
    binary = _candidate_binary()
    if binary is None:
        print(
            "seekdb binary not found. Install seekdb or set SEEKDB_BIN, or point "
            "SEEKDB_DSN at an existing OceanBase/seekdb server.",
            file=sys.stderr,
        )
        return 2
    BASE.mkdir(parents=True, exist_ok=True)
    command = [
        str(binary),
        "--base-dir",
        str(BASE),
        "--port",
        "2881",
        "--nodaemon",
        "--parameter",
        "datafile_size=5G",
        "--parameter",
        "datafile_maxsize=10G",
        "--parameter",
        "log_disk_size=2G",
    ]
    log = (BASE / "seekdb.stdout.log").open("ab")
    process = subprocess.Popen(command, cwd=str(BASE), stdout=log, stderr=log)
    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    for _ in range(60):
        if _alive():
            print(f"seekdb ready (pid={process.pid}) at 127.0.0.1:2881")
            return 0
        time.sleep(1)
    print("seekdb did not become ready; see .seekdb/seekdb.stdout.log", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
