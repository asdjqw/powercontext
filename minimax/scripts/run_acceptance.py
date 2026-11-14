"""End-to-end acceptance driver for the MiniMax SDD submission.

Run with the project venv:
    python scripts/run_acceptance.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "project"
EVIDENCE = ROOT / "evidence"
CODE_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").is_file() else "dev"
STATE_DIR = ROOT / ".state"
TARGET = PROJECT / "tests" / "test_target_minimum_discount.py"
REGRESSION = PROJECT / "tests" / "test_regression_pricing.py"
BEFORE = PROJECT / "snapshots" / "pricing_before.py"
AFTER = PROJECT / "snapshots" / "pricing_after.py"
PRICING = PROJECT / "src" / "subledger" / "pricing.py"
AMENDMENT = PROJECT / "specs" / "policy_amendment.md"
TASK = (
    "Add a minimum order threshold of 10000 cents, cap the discount at 50 percent, "
    "and preserve existing rounding and validation behavior"
)
TASK_ID = "minimax-sdd-001"


def run(command: list[str], cwd: Path, log_name: str) -> dict[str, object]:
    completed = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True)
    log = (
        f"code_version={CODE_VERSION}\n$ {' '.join(command)}\nexit_code={completed.returncode}\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}\n"
    )
    (EVIDENCE / log_name).write_text(log, encoding="utf-8")
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def cli(*args: str) -> dict[str, object]:
    return run([sys.executable, "-m", "sdd_context.cli", *args], ROOT, f"cli_{args[0]}.log")


def pytest(path: Path, phase: str) -> dict[str, object]:
    return run(
        [sys.executable, "-m", "pytest", "-q", str(path)],
        PROJECT,
        f"tests_{phase}.log",
    )


def parse_cli(result: dict[str, object]) -> dict[str, object]:
    stdout = str(result.get("stdout", ""))
    start = stdout.find("{")
    if start < 0:
        raise RuntimeError(f"CLI did not return JSON: {stdout[:500]}")
    return json.loads(stdout[start:])


def assert_true(checks: list[dict[str, object]], name: str, condition: bool, detail: object = "") -> None:
    checks.append({"check": name, "passed": bool(condition), "detail": detail})
    if not condition:
        raise AssertionError(f"{name} failed: {detail}")


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, object]] = []
    if STATE_DIR.exists():
        shutil.rmtree(STATE_DIR)
    shutil.copyfile(BEFORE, PRICING)

    # Make the demo a one-command run when a local seekdb binary is available.
    # If SEEKDB_DSN points at an external server, start_seekdb.py exits 0.
    started = run(
        [sys.executable, str(ROOT / "scripts" / "start_seekdb.py")],
        ROOT,
        "start_seekdb.log",
    )
    if started["exit_code"] != 0:
        print(
            "seekdb is not reachable. Start seekdb or set SEEKDB_DSN; see README.",
            file=sys.stderr,
        )
        return 2

    # 1. Database / index initialization and initial context.
    result = cli("db-init", "--reset")
    assert_true(checks, "seekdb init", result["exit_code"] == 0, result["stdout"][-300:])
    result = cli("import", "--reset")
    imported = parse_cli(result)
    assert_true(checks, "engineering index imported", int(imported.get("indexed", 0)) >= 7, imported)
    result = cli("context", "--task", TASK)
    context = parse_cli(result)
    (EVIDENCE / "context_initial.json").write_text(
        json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    specs_text = json.dumps(context.get("specs", []), ensure_ascii=False)
    code_paths = {item["path"] for item in context.get("code", [])}
    test_paths = {item["path"] for item in context.get("tests", [])}
    assert_true(checks, "spec PRICE-001 in context", "PRICE-001" in specs_text, specs_text[:300])
    assert_true(checks, "spec PRICE-002 in context", "PRICE-002" in specs_text, specs_text[:300])
    assert_true(
        checks,
        "pricing implementation in context",
        "project/src/subledger/pricing.py" in code_paths,
        sorted(code_paths),
    )
    assert_true(
        checks,
        "target and regression tests in context",
        "project/tests/test_target_minimum_discount.py" in test_paths
        and "project/tests/test_regression_pricing.py" in test_paths,
        sorted(test_paths),
    )
    for item in context.get("specs", []) + context.get("code", []) + context.get("tests", []):
        assert_true(checks, f"source exists {item['path']}", bool(item.get("exists")), item)

    # 2. Before-state: target fails for the intended behavioral reason, regression passes.
    before_target = pytest(TARGET, "before_target")
    before_regression = pytest(REGRESSION, "before_regression")
    assert_true(checks, "target test fails before change", before_target["exit_code"] != 0, before_target["exit_code"])
    assert_true(
        checks,
        "target failure is AssertionError",
        "AssertionError" in str(before_target["stdout"]),
        str(before_target["stdout"])[-500:],
    )
    assert_true(checks, "regression passes before change", before_regression["exit_code"] == 0, before_regression["exit_code"])

    # 3. Apply the MiniMax-generated implementation from the recorded snapshot.
    shutil.copyfile(AFTER, PRICING)
    after_target = pytest(TARGET, "after_target")
    after_regression = pytest(REGRESSION, "after_regression")
    assert_true(checks, "target test passes after change", after_target["exit_code"] == 0, after_target["stdout"][-500:])
    assert_true(checks, "regression passes after change", after_regression["exit_code"] == 0, after_regression["stdout"][-500:])

    # 4. Save validation state in PowerContext and read it in a fresh process.
    payload = {
        "task_id": TASK_ID,
        "phase": "validated",
        "completed": [
            "indexed specs, code, tests and docs in seekdb",
            "selected development context for the pricing task",
            "generated the implementation with MiniMax",
            "applied the generated implementation",
            "target and regression tests passed",
        ],
        "pending": [],
        "validation": {
            "target_tests": "pass",
            "regression_tests": "pass",
            "before_target": "fail:AssertionError",
            "after_target": "pass",
        },
        "sources": [
            "project/specs/pricing_policy.md",
            "project/specs/change_request.md",
            "project/src/subledger/pricing.py",
            "project/tests/test_target_minimum_discount.py",
            "project/tests/test_regression_pricing.py",
        ],
    }
    payload_path = EVIDENCE / "state_payload_final.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    saved = cli("state-save", "--payload-file", str(payload_path), "--task-id", TASK_ID)
    assert_true(checks, "PowerContext state saved", saved["exit_code"] == 0, saved["stdout"][-400:])
    resumed = cli("state-show", "--task-id", TASK_ID)
    restored = parse_cli(resumed)
    assert_true(checks, "PowerContext state restored after restart", restored.get("found") is True, restored)
    assert_true(
        checks,
        "restored validation matches",
        restored["state"]["validation"]["target_tests"] == "pass",
        restored["state"]["validation"],
    )

    # 5. Spec update must be visible after re-import (no fixed answer).
    original = AMENDMENT.read_text(encoding="utf-8")
    updated = original.replace("10,000 cents", "12,000 cents")
    AMENDMENT.write_text(updated, encoding="utf-8")
    try:
        imported_again = parse_cli(cli("import"))
        assert_true(checks, "re-import after spec update", imported_again.get("spec", 0) >= 3, imported_again)
        updated_context = parse_cli(cli("context", "--task", "PRICE-AMS-001 effective minimum order"))
        (EVIDENCE / "context_after_spec_update.json").write_text(
            json.dumps(updated_context, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        context_text = json.dumps(updated_context, ensure_ascii=False)
        assert_true(checks, "updated spec value returned", "12,000 cents" in context_text, context_text[-500:])
    finally:
        AMENDMENT.write_text(original, encoding="utf-8")
        cli("import")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code_version": CODE_VERSION,
        "task": TASK,
        "checks": checks,
        "passed": all(bool(item["passed"]) for item in checks),
        "total_checks": len(checks),
    }
    (EVIDENCE / "acceptance_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"passed": report["passed"], "checks": len(checks)}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
