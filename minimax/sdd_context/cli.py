"""Command line entry point for the MiniMax SDD context module."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import EVIDENCE_DIR, PROJECT_DIR, ensure_dirs
from .db import SeekdbStore
from .ingest import import_project
from .minimax_client import apply_implementation, generate_pricing_implementation
from .retrieval import build_context, render_prompt
from .state import load_task_state, save_task_state

TARGET_TESTS = PROJECT_DIR / "tests" / "test_target_minimum_discount.py"
REGRESSION_TESTS = PROJECT_DIR / "tests" / "test_regression_pricing.py"
PRICING_FILE = PROJECT_DIR / "src" / "subledger" / "pricing.py"


def _print(payload: Any, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def _run_tests(paths: list[Path], phase: str) -> dict[str, Any]:
    ensure_dirs()
    command = [sys.executable, "-m", "pytest", "-q", *[str(path) for path in paths]]
    completed = subprocess.run(
        command,
        cwd=str(PROJECT_DIR),
        text=True,
        capture_output=True,
        check=False,
    )
    log = (
        f"$ {' '.join(command)}\nexit_code={completed.returncode}\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}\n"
    )
    (EVIDENCE_DIR / f"tests_{phase}.log").write_text(log, encoding="utf-8")
    return {
        "phase": phase,
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def cmd_db_init(args: argparse.Namespace) -> int:
    store = SeekdbStore()
    try:
        store.ensure_schema()
        if args.reset:
            store.reset()
        _print({"database": store.database, "documents": store.count_documents()})
    finally:
        store.close()
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    store = SeekdbStore()
    try:
        result = import_project(store, reset=args.reset)
        _print(result)
    finally:
        store.close()
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    store = SeekdbStore()
    try:
        store.ensure_schema()
        state = None
        if args.with_state:
            state = asyncio.run(load_task_state(args.task_id))
        context = build_context(store, args.task, state=state)
        ensure_dirs()
        (EVIDENCE_DIR / "last_context.json").write_text(
            json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if args.prompt:
            print(render_prompt(context))
        else:
            _print(context)
    finally:
        store.close()
    return 0


def cmd_state_save(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    payload.setdefault("task_id", args.task_id)
    result = asyncio.run(save_task_state(payload))
    _print(result)
    return 0


def cmd_state_show(args: argparse.Namespace) -> int:
    payload = asyncio.run(load_task_state(args.task_id))
    _print({"found": payload is not None, "state": payload})
    return 0 if payload is not None else 2


def cmd_minimax_generate(args: argparse.Namespace) -> int:
    store = SeekdbStore()
    try:
        context = build_context(store, args.task)
    finally:
        store.close()
    generated = generate_pricing_implementation(
        args.task, render_prompt(context), PRICING_FILE.read_text(encoding="utf-8")
    )
    diff = apply_implementation(generated["content"], PRICING_FILE)
    ensure_dirs()
    (EVIDENCE_DIR / "minimax_patch.diff").write_text(diff, encoding="utf-8")
    (EVIDENCE_DIR / "minimax_generated_file.py").write_text(
        generated["content"], encoding="utf-8"
    )
    _print(
        {
            "model": generated.get("model"),
            "summary": generated.get("summary"),
            "usage": generated.get("usage"),
            "file": str(PRICING_FILE.relative_to(PROJECT_DIR.parent)),
            "diff_path": str((EVIDENCE_DIR / "minimax_patch.diff").relative_to(PROJECT_DIR.parent)),
            "content_sha256": __import__("hashlib").sha256(
                generated["content"].encode()
            ).hexdigest(),
        }
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    target = _run_tests([TARGET_TESTS], f"{args.phase}_target")
    regression = _run_tests([REGRESSION_TESTS], f"{args.phase}_regression")
    _print({"target": target, "regression": regression})
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    import shutil

    before = PROJECT_DIR / "snapshots" / "pricing_before.py"
    shutil.copyfile(before, PRICING_FILE)
    store = SeekdbStore()
    try:
        import_project(store, reset=True)
    finally:
        store.close()
    _print({"pricing_restored": str(before), "index": "rebuilt"})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sdd-context")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("db-init")
    p.add_argument("--reset", action="store_true")
    p.set_defaults(func=cmd_db_init)

    p = sub.add_parser("import")
    p.add_argument("--reset", action="store_true")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("context")
    p.add_argument("--task", required=True)
    p.add_argument("--with-state", action="store_true")
    p.add_argument("--task-id", default="minimax-sdd-001")
    p.add_argument("--prompt", action="store_true")
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("state-save")
    p.add_argument("--payload-file", required=True)
    p.add_argument("--task-id", default="minimax-sdd-001")
    p.set_defaults(func=cmd_state_save)

    p = sub.add_parser("state-show")
    p.add_argument("--task-id", default="minimax-sdd-001")
    p.set_defaults(func=cmd_state_show)

    p = sub.add_parser("minimax-generate")
    p.add_argument("--task", required=True)
    p.set_defaults(func=cmd_minimax_generate)

    p = sub.add_parser("verify")
    p.add_argument("--phase", choices=["before", "after"], required=True)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("reset")
    p.set_defaults(func=cmd_reset)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
