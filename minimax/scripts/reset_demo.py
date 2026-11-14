"""Reset the demo to the before-state and rebuild the seekdb index."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdd_context.db import SeekdbStore  # noqa: E402
from sdd_context.ingest import import_project  # noqa: E402

PROJECT = ROOT / "project"
BEFORE = PROJECT / "snapshots" / "pricing_before.py"
AFTER = PROJECT / "snapshots" / "pricing_after.py"
PRICING = PROJECT / "src" / "subledger" / "pricing.py"


def main() -> int:
    shutil.copyfile(BEFORE, PRICING)
    shutil.rmtree(ROOT / ".state", ignore_errors=True)
    store = SeekdbStore()
    try:
        result = import_project(store, reset=True)
    finally:
        store.close()
    print({"pricing": "before", "index": result, "state": "cleared"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
