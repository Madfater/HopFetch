"""Mechanical checks for the repository rules in CLAUDE.md.

- Rule 1 (no emoji): fails on any emoji in added lines.
- Rule 2 (no history in code): warns on added comment lines that read as change history.
  This is a heuristic; the code-reviewer agent judges it semantically.
- Rule 4 (knowledge in docs/): fails on new Markdown files outside `docs/`, except
  README.md, CLAUDE.md, and files under `.claude/` or `.github/`.
- Rule 5 (scripts in script/): fails on new shell or batch scripts outside `script/`,
  and on any new file under a `scripts/` directory.
- Exits 1 when any failure is found; warnings alone exit 0.

Usage:
    python3 script/check_conventions.py --staged        # staged changes, used before each commit
    python3 script/check_conventions.py --base <ref>    # changes since merge-base with ref, used in CI
    python3 script/check_conventions.py --all           # every tracked file
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U00002B00-\U00002BFF"
    "\U0000231A-\U0000231B"
    "\U000023E9-\U000023FA"
    "\U0000FE0F"
    "\U0000200D"
    "]"
)

HISTORY_PATTERN = re.compile(
    r"\b("
    r"previously|formerly|used to|no longer|anymore|was changed|changed from|changed to|"
    r"was renamed|renamed from|was removed|removed the|replaced by|replaced with|"
    r"old (?:code|version|implementation|behavio(?:u)?r)|legacy|"
    r"(?:bug ?)?fix(?:ed)? for|workaround for issue|added in v?\d|since v?\d"
    r")\b",
    re.IGNORECASE,
)

COMMENT_PREFIXES = ("#", "//", "/*", "*", "--", "<!--", ";")
TRAILING_COMMENT = re.compile(r"(?:\s#\s|\s//\s)(.*)$")
CODE_SUFFIXES = {
    ".py", ".sh", ".bash", ".zsh", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs",
    ".java", ".kt", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift", ".lua",
    ".sql", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".tf", ".css", ".scss", ".vue", ".svelte",
}
SCRIPT_SUFFIXES = {".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd"}
DOC_ALLOWED_NAMES = {"README.md", "CLAUDE.md"}
DOC_ALLOWED_ROOTS = {".claude", ".github"}
SKIP_EMOJI_PATHS = {"script/check_conventions.py"}


@dataclass
class Issue:
    """One finding: severity is `error` or `warning`."""

    severity: str
    path: str
    line: int
    message: str

    def render(self) -> str:
        """Format as `severity path:line message`."""
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.severity}: {where} {self.message}"


def git(args: list[str]) -> str:
    """Run git and return stdout; exit with git's stderr on failure."""
    proc = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def parse_diff(diff: str) -> dict[str, list[tuple[int, str]]]:
    """Map each file in a unified diff (`-U0`) to its added lines as (line number, text).

    - A `diff --git` line starts a file header; `+++ b/<path>` is read only inside that header,
      so an added line whose content starts with `++ ` is not mistaken for a header.
    - Each `@@ ... +start,count @@` hunk header ends the file header and sets the line counter.
    - Deleted files (`+++ /dev/null`) are skipped.
    """
    added: dict[str, list[tuple[int, str]]] = {}
    current: str | None = None
    in_header = False
    line_no = 0
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            in_header = True
            current = None
            continue
        if in_header and raw.startswith("+++ "):
            target = raw[4:]
            current = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            if current is not None:
                added.setdefault(current, [])
            continue
        if raw.startswith("@@"):
            in_header = False
            match = re.search(r"\+(\d+)", raw)
            line_no = int(match.group(1)) if match else 0
            continue
        if current is None or in_header:
            continue
        if raw.startswith("+"):
            added[current].append((line_no, raw[1:]))
            line_no += 1
        elif raw.startswith(" "):
            line_no += 1
    return added


def comment_text(path: str, line: str) -> str | None:
    """Return the comment part of a source line, or None when the line has no comment.

    - Full-line comments use the prefixes in COMMENT_PREFIXES.
    - Trailing comments are recognised for ` # ` and ` // `.
    - Only applies to files whose suffix is in CODE_SUFFIXES.
    """
    if PurePosixPath(path).suffix.lower() not in CODE_SUFFIXES:
        return None
    stripped = line.strip()
    if stripped.startswith(COMMENT_PREFIXES):
        return stripped
    match = TRAILING_COMMENT.search(line)
    return match.group(1) if match else None


def check_lines(path: str, lines: list[tuple[int, str]]) -> list[Issue]:
    """Apply the emoji and history-comment checks to one file's added lines."""
    issues: list[Issue] = []
    for number, text in lines:
        if path not in SKIP_EMOJI_PATHS and EMOJI_PATTERN.search(text):
            issues.append(Issue("error", path, number, "contains emoji (rule 1)"))
        comment = comment_text(path, text)
        if comment:
            match = HISTORY_PATTERN.search(comment)
            if match:
                issues.append(Issue(
                    "warning", path, number,
                    f"comment reads as history ('{match.group(0)}'); describe current behavior only (rule 2)",
                ))
    return issues


def check_placement(path: str) -> list[Issue]:
    """Apply the docs/ and script/ placement rules to one newly added file."""
    parts = PurePosixPath(path).parts
    name = parts[-1]
    suffix = PurePosixPath(path).suffix.lower()
    issues: list[Issue] = []
    if suffix == ".md" and parts[0] != "docs" and name not in DOC_ALLOWED_NAMES and parts[0] not in DOC_ALLOWED_ROOTS:
        issues.append(Issue("error", path, 0, "knowledge files belong under docs/ (rule 4)"))
    if "scripts" in parts[:-1]:
        issues.append(Issue("error", path, 0, "use script/ (singular), not scripts/ (rule 5)"))
    elif suffix in SCRIPT_SUFFIXES and parts[0] != "script":
        issues.append(Issue("error", path, 0, "scripts belong under script/ (rule 5)"))
    return issues


def collect(mode: str, base: str | None) -> tuple[dict[str, list[tuple[int, str]]], list[str]]:
    """Return added lines per file and the list of newly added paths for the chosen mode.

    - `staged`: the index against HEAD.
    - `base`: HEAD against its merge-base with the given ref.
    - `all`: every tracked file, with every line treated as added.
    """
    if mode == "all":
        files = [f for f in git(["ls-files"]).splitlines() if f]
        added: dict[str, list[tuple[int, str]]] = {}
        for path in files:
            try:
                with open(path, encoding="utf-8") as handle:
                    added[path] = list(enumerate(handle.read().splitlines(), start=1))
            except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
                continue
        return added, files
    range_args = ["--cached"] if mode == "staged" else [f"{base}...HEAD"]
    diff = git(["diff", "-U0", "--no-color", "--no-ext-diff", "--text", *range_args])
    new_files = git(["diff", "--name-only", "--diff-filter=A", *range_args]).splitlines()
    return parse_diff(diff), [f for f in new_files if f]


def main(argv: list[str] | None = None) -> int:
    """Run all checks, print findings and return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true")
    group.add_argument("--base")
    group.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    mode = "all" if args.all else "staged" if args.staged else "base"
    added, new_files = collect(mode, args.base)

    issues: list[Issue] = []
    for path, lines in sorted(added.items()):
        issues.extend(check_lines(path, lines))
    for path in sorted(new_files):
        issues.extend(check_placement(path))

    for issue in issues:
        print(issue.render())
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = len(issues) - errors
    print(f"check_conventions: {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
