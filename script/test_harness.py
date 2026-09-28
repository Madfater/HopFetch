"""Self-tests for the harness scripts, run by script/check.py.

- Covers pure logic only: no network access and no changes outside temporary directories.
- Run directly with: python3 -m unittest discover -s script -p "test_*.py"
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply  # noqa: E402
import check_conventions as cc  # noqa: E402
import github  # noqa: E402


class ParseEnvFileTest(unittest.TestCase):
    """Behavior of github.parse_env_file."""

    def test_parses_keys_quotes_comments_and_export(self):
        text = "# comment\n\nGITHUB_TOKEN='abc'\nexport GITHUB_REPO=\"o/r\"\nBROKEN\nEMPTY=\n"
        self.assertEqual(
            github.parse_env_file(text),
            {"GITHUB_TOKEN": "abc", "GITHUB_REPO": "o/r", "EMPTY": ""},
        )


class ParseRemoteUrlTest(unittest.TestCase):
    """Behavior of github.parse_remote_url."""

    def test_supported_forms(self):
        for url in (
            "https://github.com/Owner/repo.git",
            "https://github.com/Owner/repo",
            "https://user@github.com/Owner/repo.git",
            "git@github.com:Owner/repo.git",
            "ssh://git@github.com/Owner/repo",
        ):
            with self.subTest(url=url):
                self.assertEqual(github.parse_remote_url(url), "Owner/repo")

    def test_non_github_remote(self):
        self.assertIsNone(github.parse_remote_url("https://gitlab.com/o/r.git"))


class SummarizeChecksTest(unittest.TestCase):
    """Behavior of github.summarize_checks."""

    def run_(self, status, conclusion=None):
        return {"name": "ci", "status": status, "conclusion": conclusion, "html_url": ""}

    def test_none(self):
        self.assertEqual(github.summarize_checks([], [])["overall"], "none")

    def test_pending_wins_over_failure(self):
        runs = [self.run_("in_progress"), self.run_("completed", "failure")]
        self.assertEqual(github.summarize_checks(runs, [])["overall"], "pending")

    def test_failure(self):
        runs = [self.run_("completed", "success")]
        statuses = [{"context": "legacy", "state": "error", "target_url": ""}]
        self.assertEqual(github.summarize_checks(runs, statuses)["overall"], "failure")

    def test_success_with_skipped(self):
        runs = [self.run_("completed", "success"), self.run_("completed", "skipped")]
        self.assertEqual(github.summarize_checks(runs, [])["overall"], "success")


class IssueRecordTest(unittest.TestCase):
    """Behavior of github.only_issues and github.issue_record."""

    ISSUE = {
        "number": 7, "title": "Crash on save", "state": "open", "user": {"login": "amy"},
        "labels": [{"name": "bug"}], "assignees": [{"login": "bo"}],
        "html_url": "https://github.com/o/r/issues/7", "body": None,
    }

    def test_only_issues_drops_pull_requests(self):
        items = [self.ISSUE, {**self.ISSUE, "number": 8, "pull_request": {}}]
        self.assertEqual([i["number"] for i in github.only_issues(items)], [7])

    def test_record_fields_and_comments(self):
        record = github.issue_record(self.ISSUE, [{"user": None, "created_at": "t", "body": "hi"}])
        self.assertEqual(record["labels"], ["bug"])
        self.assertEqual(record["assignees"], ["bo"])
        self.assertEqual(record["body"], "")
        self.assertEqual(record["comments"], [{"author": None, "created_at": "t", "body": "hi"}])

    def test_record_without_comments_has_no_comment_key(self):
        self.assertNotIn("comments", github.issue_record(self.ISSUE))


class FakeClient:
    """Stand-in for github.Client that serves canned pages for the issues listing."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = 0

    def request(self, method, path, body=None):
        self.calls += 1
        return self.pages[self.calls - 1]


class IssueListTest(unittest.TestCase):
    """Behavior of github.cmd_issue_list and error exit codes in github.main."""

    def args(self, limit):
        return type("Args", (), {"limit": limit, "state": "open", "label": None, "assignee": None})()

    def item(self, number, pr=False):
        item = dict(IssueRecordTest.ISSUE, number=number)
        if pr:
            item["pull_request"] = {}
        return item

    def test_pages_past_pull_requests_until_limit(self):
        first = [self.item(n, pr=True) for n in range(99)] + [self.item(1000)]
        second = [self.item(1001), self.item(1002)]
        client = FakeClient([first, second])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            github.cmd_issue_list(client, self.args(2))
        self.assertEqual([i["number"] for i in json.loads(out.getvalue())], [1000, 1001])
        self.assertEqual(client.calls, 2)

    def test_limit_below_one_is_an_error(self):
        with self.assertRaises(github.GitHubError):
            github.cmd_issue_list(FakeClient([]), self.args(0))

    def test_unreadable_body_file_exits_3(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = github.main(["issue-comment", "--number", "1", "--body-file", "/nonexistent/body.md"])
        self.assertEqual(code, 3)


class ParseDiffTest(unittest.TestCase):
    """Behavior of check_conventions.parse_diff."""

    def test_added_lines_with_numbers(self):
        diff = (
            "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n"
            "@@ -1,0 +2,2 @@\n+one\n+two\n"
            "diff --git a/gone.py b/gone.py\n--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-bye\n"
        )
        self.assertEqual(cc.parse_diff(diff), {"x.py": [(2, "one"), (3, "two")]})

    def test_added_line_that_looks_like_header(self):
        diff = "diff --git a/x.md b/x.md\n--- a/x.md\n+++ b/x.md\n@@ -0,0 +1,2 @@\n+++ b\n+after\n"
        self.assertEqual(cc.parse_diff(diff), {"x.md": [(1, "++ b"), (2, "after")]})


class LineChecksTest(unittest.TestCase):
    """Behavior of check_conventions.check_lines."""

    def test_emoji_is_error(self):
        issues = cc.check_lines("a.md", [(1, "done " + chr(0x2705))])
        self.assertEqual([i.severity for i in issues], ["error"])

    def test_plain_arrows_and_punctuation_pass(self):
        self.assertEqual(cc.check_lines("a.md", [(1, "a -> b, 50% (ok) " + chr(0x2192) + " c")]), [])

    def test_history_comment_is_warning(self):
        issues = cc.check_lines("a.py", [(1, "x = 1  #" + " previously this was 2")])
        self.assertEqual([i.severity for i in issues], ["warning"])

    def test_history_word_outside_comment_passes(self):
        self.assertEqual(cc.check_lines("a.py", [(1, "legacy = load()")]), [])

    def test_history_in_markdown_is_not_checked(self):
        self.assertEqual(cc.check_lines("docs/a.md", [(1, "# " + "previously")]), [])


class PlacementTest(unittest.TestCase):
    """Behavior of check_conventions.check_placement."""

    def errors(self, path):
        return [i.message for i in cc.check_placement(path)]

    def test_allowed(self):
        for path in ("docs/x.md", "README.md", "pkg/README.md", "CLAUDE.md",
                     ".claude/skills/a/SKILL.md", ".github/PULL_REQUEST_TEMPLATE.md",
                     "script/run.sh", "src/app.py"):
            with self.subTest(path=path):
                self.assertEqual(self.errors(path), [])

    def test_rejected(self):
        for path in ("notes.md", "src/DESIGN.md", "deploy.sh", "tools/x.ps1", "scripts/x.py"):
            with self.subTest(path=path):
                self.assertEqual(len(self.errors(path)), 1)


class ApplyPlanTest(unittest.TestCase):
    """Behavior of apply.plan and apply.apply against a scratch repository."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.target = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.target)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def kinds(self, actions):
        return {a.path: a.kind for a in actions}

    def test_fresh_target_creates_everything(self):
        kinds = self.kinds(apply.plan(self.target))
        for rel in apply.expand(apply.TEMPLATE_OWNED) + apply.PROJECT_OWNED + [".gitignore", apply.VERSION_FILE]:
            self.assertIn(kinds[rel], {"create", "append"}, rel)

    def test_second_run_is_idempotent(self):
        apply.apply(self.target, apply.plan(self.target))
        kinds = self.kinds(apply.plan(self.target))
        self.assertEqual(set(kinds.values()), {"skip"})

    def test_customised_project_file_gets_template_copy(self):
        (self.target / "CLAUDE.md").write_text("custom\n", encoding="utf-8")
        apply.apply(self.target, apply.plan(self.target))
        self.assertEqual((self.target / "CLAUDE.md").read_text(encoding="utf-8"), "custom\n")
        self.assertTrue((self.target / "CLAUDE.md.template").is_file())
        self.assertEqual(self.kinds(apply.plan(self.target))["CLAUDE.md"], "skip")

    def test_directory_entry_expands_to_its_files(self):
        files = apply.expand([".claude/skills/playwright-cli/"])
        self.assertIn(".claude/skills/playwright-cli/SKILL.md", files)
        self.assertTrue(any(f.startswith(".claude/skills/playwright-cli/references/") for f in files))
        self.assertTrue(all(not f.endswith("/") for f in files))

    def test_customised_template_file_is_overwritten(self):
        path = self.target / "script/github.py"
        path.parent.mkdir(parents=True)
        path.write_text("old\n", encoding="utf-8")
        self.assertEqual(self.kinds(apply.plan(self.target))["script/github.py"], "update")

    def test_gitignore_keeps_existing_lines(self):
        (self.target / ".gitignore").write_text("node_modules/\n.env.skills", encoding="utf-8")
        apply.apply(self.target, apply.plan(self.target))
        lines = (self.target / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "node_modules/")
        self.assertEqual(lines.count(".env.skills"), 1)
        self.assertIn(".claude/worktrees/", lines)


if __name__ == "__main__":
    unittest.main()
