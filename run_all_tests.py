"""Run every chapter's test suite, each in its own pytest process.

`uv run pytest` already runs all 11 chapters in one process (root conftest.py
gives each chapter a private import root). This script is the *isolation* view:
pytest once per chapter, in its own directory, exactly the way the book does it
(`cd ch09 && pytest`). If something only fails in the combined run, compare the
two.

    uv run python run_all_tests.py
"""

import subprocess
import sys
from pathlib import Path

CHAPTERS = ["ch01", "ch03", "ch04", "ch05", "ch06", "ch07", "ch08", "ch09", "ch10", "ch11", "ch12"]

ROOT = Path(__file__).parent


def main():
    results = []
    total = len(CHAPTERS)

    for index, chapter in enumerate(CHAPTERS, start=1):
        directory = ROOT / chapter
        tests = sorted(directory.glob("test_*.py"))
        if not tests:
            print(f"[{index}/{total}] {chapter}: no tests, skipped")
            continue

        print(f"[{index}/{total}] {chapter}: {', '.join(t.name for t in tests)}", flush=True)
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *[t.name for t in tests]],
            cwd=directory,
            capture_output=True,
            text=True,
        )
        tail = (proc.stdout or proc.stderr).strip().splitlines()
        summary = tail[-1] if tail else f"exit {proc.returncode}"
        ok = proc.returncode == 0
        results.append((chapter, ok, summary))
        print(f"          {'PASS' if ok else 'FAIL'} - {summary}", flush=True)

    failures = [r for r in results if not r[1]]
    print()
    print(f"{len(results) - len(failures)}/{len(results)} chapters green")
    for chapter, _, summary in failures:
        print(f"  FAIL {chapter}: {summary}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
