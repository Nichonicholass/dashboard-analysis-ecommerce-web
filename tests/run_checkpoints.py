"""Checkpoint runner.

Reads `checkpoint.json`, executes each checkpoint's single test method in isolation,
prints a summary, writes pass/fail back into the manifest, and exits non-zero if any
checkpoint fails.

Usage
-----
    python tests/run_checkpoints.py               # run everything
    python tests/run_checkpoints.py --category run_rate
    python tests/run_checkpoints.py --id CP-11 CP-36
    python tests/run_checkpoints.py --no-write    # dry run, leave the manifest alone

Why run from the manifest rather than `python -m unittest discover`?
------------------------------------------------------------------
The manifest is the source of truth for *what is being verified and why*. Running one
test method per checkpoint means a checkpoint cannot silently disappear, and each
result can be attributed back to a spec section.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"

# `metrics` lives in src/, the test modules live in tests/.
for path in (str(SRC), str(TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

MANIFEST_PATH = ROOT / "checkpoint.json"

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_ERROR = "error"

# Colour-free symbols so output is readable in any terminal and in CI logs.
MARK = {STATUS_PASSED: "PASS", STATUS_FAILED: "FAIL", STATUS_ERROR: "ERROR"}


def load_manifest() -> dict:
    with MANIFEST_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_manifest(manifest: dict) -> None:
    with MANIFEST_PATH.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _resolve_test_method(testname: str) -> Tuple[str, str]:
    """Split `TestClass.test_method` into its parts."""
    if "." not in testname:
        raise ValueError(f"testname must be 'TestClass.method', got {testname!r}")
    class_name, method_name = testname.rsplit(".", 1)
    return class_name, method_name


def run_checkpoint(checkpoint: dict) -> Tuple[str, str, float]:
    """Execute one checkpoint. Returns (status, message, seconds)."""
    file_path = ROOT / checkpoint["file"]
    class_name, method_name = _resolve_test_method(checkpoint["testname"])

    module_name = file_path.stem
    started = time.perf_counter()

    try:
        module = importlib.import_module(module_name)
        importlib.reload(module)
    except Exception as exc:  # import failure = the logic under test doesn't exist yet
        elapsed = time.perf_counter() - started
        return STATUS_ERROR, f"{type(exc).__name__}: {exc}", elapsed

    test_class = getattr(module, class_name, None)
    if test_class is None:
        elapsed = time.perf_counter() - started
        return STATUS_ERROR, f"{class_name} not found in {checkpoint['file']}", elapsed

    # Run just this one method, so checkpoints stay independently attributable.
    suite = unittest.TestSuite([test_class(method_name)])
    result = unittest.TestResult()
    suite.run(result)

    elapsed = time.perf_counter() - started

    if result.wasSuccessful():
        return STATUS_PASSED, "", elapsed

    if result.errors:
        _, traceback_text = result.errors[0]
        return STATUS_ERROR, traceback_text.strip().splitlines()[-1], elapsed

    if result.failures:
        _, traceback_text = result.failures[0]
        last_line = traceback_text.strip().splitlines()[-1]
        return STATUS_FAILED, last_line, elapsed

    return STATUS_FAILED, "unknown failure", elapsed


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run checkpoints from checkpoint.json")
    parser.add_argument("--category", action="append", default=None,
                        help="only run this category (repeatable)")
    parser.add_argument("--id", nargs="+", default=None,
                        help="only run these checkpoint IDs")
    parser.add_argument("--no-write", action="store_true",
                        help="do not write results back into checkpoint.json")
    args = parser.parse_args(argv)

    manifest = load_manifest()
    checkpoints: List[dict] = manifest.get("checkpoints", [])

    if args.category:
        wanted = set(args.category)
        checkpoints = [c for c in checkpoints if c.get("category") in wanted]
    if args.id:
        wanted_ids = set(args.id)
        checkpoints = [c for c in checkpoints if c.get("id") in wanted_ids]

    if not checkpoints:
        print("No checkpoints matched the filter.")
        return 1

    print(f"Running {len(checkpoints)} checkpoints from {MANIFEST_PATH.name}\n")

    counts: Dict[str, int] = {STATUS_PASSED: 0, STATUS_FAILED: 0, STATUS_ERROR: 0}
    total_seconds = 0.0
    current_category = None

    for checkpoint in checkpoints:
        category = checkpoint.get("category", "uncategorised")
        if category != current_category:
            current_category = category
            print(f"  {category}")
        status, message, elapsed = run_checkpoint(checkpoint)
        counts[status] += 1
        total_seconds += elapsed

        checkpoint["status"] = status
        checkpoint["duration_ms"] = round(elapsed * 1000, 2)
        checkpoint["message"] = message

        line = (f"    [{MARK[status]}] {checkpoint['id']}  {checkpoint['title']}"
                f"  ({checkpoint.get('spec_ref', '')})")
        print(line)
        if message:
            print(f"           {message}")

    passed = counts[STATUS_PASSED]
    failed = counts[STATUS_FAILED] + counts[STATUS_ERROR]

    print(f"\n{'-' * 74}")
    print(f"{passed} passed, {failed} failed, {len(checkpoints)} total"
          f"  ({total_seconds:.2f}s)")

    if not args.no_write:
        manifest["last_run"] = {
            "passed": passed,
            "failed": failed,
            "total": len(checkpoints),
            "duration_seconds": round(total_seconds, 2),
        }
        save_manifest(manifest)
        print(f"Results written back to {MANIFEST_PATH.name}")

    if failed:
        print("\nFailing checkpoints:")
        for checkpoint in checkpoints:
            if checkpoint.get("status") in (STATUS_FAILED, STATUS_ERROR):
                print(f"  {checkpoint['id']}  {checkpoint['title']}")
                if checkpoint.get("message"):
                    print(f"        {checkpoint['message']}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())