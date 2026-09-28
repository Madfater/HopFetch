"""Install or update the harness in another repository from this local clone.

- Template-owned files are overwritten in the target, so re-running pulls in template updates.
- A template-owned entry ending in `/` is a directory: every file under it is template-owned.
- Project-owned files are created only when missing. When the target already has a different
  version, the template version is written next to it as `<file>.template` for a human to merge.
- `.gitignore` gets any missing harness entries appended; existing lines are kept.
- `.claude/harness-version` records the template commit the target was synced from.
- Files whose content already matches are left alone.
- Prints the plan and asks for confirmation before writing (human in the loop).
  `--dry-run` prints the plan only; `--yes` skips the prompt after a human approved the plan.
- Without a terminal and without `--yes`, the prompt reads end of input and aborts.

Usage:
    python3 script/apply.py <target-repo> --dry-run
    python3 script/apply.py <target-repo> [--yes]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent

TEMPLATE_OWNED = [
    ".claude/skills/ship/SKILL.md",
    ".claude/skills/land/SKILL.md",
    ".claude/skills/issue/SKILL.md",
    ".claude/skills/playwright-cli/",
    ".claude/agents/code-reviewer.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".env.skills.example",
    "docs/workflow.md",
    "docs/setup.md",
    "script/apply.py",
    "script/check_conventions.py",
    "script/github.py",
    "script/test_harness.py",
]

PROJECT_OWNED = [
    "CLAUDE.md",
    ".claude/settings.json",
    ".github/workflows/harness.yml",
    ".playwright/cli.config.json",
    "docs/README.md",
    "docs/architecture.md",
    "script/check.py",
]

GITIGNORE_LINES = [
    ".env.skills",
    ".claude/worktrees/",
    ".claude/settings.local.json",
    "__pycache__/",
    ".playwright-cli/",
]

VERSION_FILE = ".claude/harness-version"


@dataclass
class Action:
    """One planned change: kind is create, update, template, append or skip."""

    kind: str
    path: str
    detail: str = ""


def template_commit() -> str:
    """Return the template clone's HEAD commit, marked `-dirty` when it has local changes."""
    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(TEMPLATE_ROOT), *args], capture_output=True, text=True, check=False
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""

    sha = git("rev-parse", "--verify", "--quiet", "HEAD") or "unknown"
    dirty = bool(git("status", "--porcelain"))
    return f"{sha}-dirty" if dirty else sha


def read_bytes(path: Path) -> bytes | None:
    """Return file content, or None when the file does not exist."""
    return path.read_bytes() if path.is_file() else None


def expand(entries: list[str]) -> list[str]:
    """Replace each directory entry (trailing `/`) with the sorted files under it in the template.

    - Uses `git ls-files` so untracked and ignored files in the template are never copied.
    - Falls back to walking the directory when the template is not a git checkout.
    """
    files: list[str] = []
    for entry in entries:
        if not entry.endswith("/"):
            files.append(entry)
            continue
        root = TEMPLATE_ROOT / entry
        if not root.is_dir():
            raise SystemExit(f"template directory missing: {entry}")
        proc = subprocess.run(
            ["git", "-C", str(TEMPLATE_ROOT), "ls-files", "--", entry],
            capture_output=True, text=True, check=False,
        )
        tracked = sorted(line for line in proc.stdout.splitlines() if line)
        if proc.returncode == 0 and tracked:
            files.extend(tracked)
        else:
            files.extend(
                path.relative_to(TEMPLATE_ROOT).as_posix()
                for path in sorted(root.rglob("*"))
                if path.is_file() and "__pycache__" not in path.parts
            )
    return files


def plan(target: Path) -> list[Action]:
    """Compare the template with the target and list the changes to make."""
    actions: list[Action] = []
    for rel in expand(TEMPLATE_OWNED):
        src = read_bytes(TEMPLATE_ROOT / rel)
        if src is None:
            raise SystemExit(f"template file missing: {rel}")
        dst = read_bytes(target / rel)
        if dst is None:
            actions.append(Action("create", rel))
        elif dst != src:
            actions.append(Action("update", rel))
        else:
            actions.append(Action("skip", rel, "identical"))
    for rel in PROJECT_OWNED:
        src = read_bytes(TEMPLATE_ROOT / rel)
        if src is None:
            raise SystemExit(f"template file missing: {rel}")
        dst = read_bytes(target / rel)
        if dst is None:
            actions.append(Action("create", rel))
        elif dst == src:
            actions.append(Action("skip", rel, "identical"))
        elif read_bytes(target / f"{rel}.template") == src:
            actions.append(Action("skip", rel, "project-owned, .template already current"))
        else:
            actions.append(Action("template", rel, f"exists, writing {rel}.template to merge by hand"))
    existing = (target / ".gitignore").read_text(encoding="utf-8").splitlines() if (target / ".gitignore").is_file() else []
    missing = [line for line in GITIGNORE_LINES if line not in {e.strip() for e in existing}]
    if missing:
        actions.append(Action("append", ".gitignore", ", ".join(missing)))
    commit = template_commit()
    current = read_bytes(target / VERSION_FILE)
    if current is None:
        actions.append(Action("create", VERSION_FILE, commit))
    elif current.decode(errors="replace").strip() != commit:
        actions.append(Action("update", VERSION_FILE, commit))
    else:
        actions.append(Action("skip", VERSION_FILE, "identical"))
    return actions


def apply(target: Path, actions: list[Action]) -> None:
    """Carry out the planned actions in the target."""
    for action in actions:
        dst = target / action.path
        if action.kind in {"create", "update"} and action.path == VERSION_FILE:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(action.detail + "\n", encoding="utf-8")
        elif action.kind in {"create", "update"}:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes((TEMPLATE_ROOT / action.path).read_bytes())
            if action.path.startswith("script/") and action.path.endswith(".py"):
                dst.chmod(0o755)
        elif action.kind == "template":
            (target / f"{action.path}.template").write_bytes((TEMPLATE_ROOT / action.path).read_bytes())
        elif action.kind == "append":
            text = dst.read_text(encoding="utf-8") if dst.is_file() else ""
            if text and not text.endswith("\n"):
                text += "\n"
            lines = [line for line in GITIGNORE_LINES if line in action.detail.split(", ")]
            dst.write_text(text + "\n".join(lines) + "\n", encoding="utf-8")


def render(actions: list[Action]) -> str:
    """Format the plan as aligned lines, hiding identical files."""
    rows = [a for a in actions if a.kind != "skip"]
    skipped = len(actions) - len(rows)
    lines = [f"  {a.kind:<9} {a.path}" + (f"  ({a.detail})" if a.detail else "") for a in rows]
    lines.append(f"  {skipped} file(s) already up to date")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Validate the target, show the plan, confirm, and apply."""
    parser = argparse.ArgumentParser(description="Install or update the harness in a repository.")
    parser.add_argument("target")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser().resolve()
    if not target.is_dir():
        print(f"error: {target} is not a directory", file=sys.stderr)
        return 1
    if target == TEMPLATE_ROOT:
        print("error: target is the template itself", file=sys.stderr)
        return 1
    if not (target / ".git").exists():
        print(f"error: {target} is not a git repository", file=sys.stderr)
        return 1

    actions = plan(target)
    print(f"Harness plan for {target}:")
    print(render(actions))
    if args.dry_run:
        return 0
    if all(a.kind == "skip" for a in actions):
        print("nothing to do.")
        return 0
    if not args.yes:
        try:
            answer = input("Apply these changes? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in {"y", "yes"}:
            print("aborted")
            return 1
    apply(target, actions)
    templates = [a.path for a in actions if a.kind == "template"]
    print("applied.")
    if templates:
        print("Merge these by hand, then delete the .template files:")
        for path in templates:
            print(f"  {path}.template -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
