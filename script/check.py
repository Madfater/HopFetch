"""Single entrypoint for the project's checks, run by /ship before each commit and by CI.

- Runs HARNESS_COMMANDS first: the self-tests of the harness scripts.
- Runs PROJECT_COMMANDS next: fill these in with the project's lint, typecheck and test commands.
- Runs every command from the repository root and stops at the first failure.
- When PROJECT_COMMANDS is empty, prints an `UNCONFIGURED` warning; /ship treats that as a stop
  and asks the human to fill it in. See docs/workflow.md for examples per stack.

Usage:
    python3 script/check.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HARNESS_COMMANDS: list[list[str]] = [
    [sys.executable, "-m", "unittest", "discover", "-s", "script", "-p", "test_*.py", "-q"],
]

PROJECT_COMMANDS: list[list[str]] = [
    ["uv", "run", "--locked", "pytest", "-q"],
]


def run(command: list[str]) -> int:
    """Print and run one command, returning its exit code."""
    print(f"$ {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main() -> int:
    """Run all commands in order and report the result."""
    for command in HARNESS_COMMANDS + PROJECT_COMMANDS:
        code = run(command)
        if code != 0:
            print(f"check: FAILED ({' '.join(command)} exited {code})")
            return code
    if not PROJECT_COMMANDS:
        print("check: UNCONFIGURED - add the project's lint, typecheck and test commands to "
              "PROJECT_COMMANDS in script/check.py")
        return 0
    print("check: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
