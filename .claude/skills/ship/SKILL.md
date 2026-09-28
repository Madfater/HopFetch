---
name: ship
description: "Ship a change end to end: agreed scope, worktree branch, checked commits, fresh-context review, PR from the template, CI, then human-judged docs. Stops before anything leaves the machine. Never merges."
argument-hint: "What are you shipping?"
disable-model-invocation: true
---

# Ship

Nine gates carry a change from an idea to an open, reviewed PR. Each gate ends on a **check**: a command you run and read, never an assumption. A gate opens only when the previous check passed.

The Human in the loop rule from CLAUDE.md governs every gate. Local work runs without asking. Stop and wait for an explicit yes before:
- anything that leaves the machine: push, PR create, PR edit;
- anything irreversible: deletes, force operations, history rewrites;
- continuing after a check or review still fails past its retry budget.

A yes covers only the action it was asked for. Merging is always the human's act on GitHub; this skill never merges.

All GitHub access goes through `python3 script/github.py`, which reads credentials from `.env.skills`. Never read or print that file.

## Gate 0 - Locate

Resuming mid-flow is normal. Find where the repo is before doing anything:

```bash
git worktree list && git status --short && git branch --show-current
python3 script/github.py pr-view      # exits 3 with "No PR found" when the branch has none
```

| What you see | Resume at |
| --- | --- |
| On the default branch, no task agreed | 1 |
| On a feature branch in a worktree, no PR | 3, 4 or 5, by what the log and criteria show |
| PR open, checks not reported | 7 |
| PR open, checks green, docs not decided | 8 |
| PR open, docs decided | 9 |

State the gate and why before continuing.

## Gate 1 - Scope (human in the loop)

Present, then wait for yes:
- The task in one or two sentences.
- Branch name `<type>/<kebab-summary>`, type one of `feat`, `fix`, `docs`, `chore`, `refactor`.
- Acceptance criteria, numbered, each tagged `runnable` (with the exact command that proves it) or `judgment`.
- Whether the change touches a runnable app or a web UI, which decides the `/verify` and browser steps in gate 4.
- For a web UI change, the pages and states to check, each listed as a `judgment` criterion. Examples are the layout at desktop and mobile widths, empty and error states, and keyboard focus.

Run `python3 script/check.py`. If it prints `UNCONFIGURED`, say so. Ask the human to add the project's commands to `PROJECT_COMMANDS`, or to confirm that the repo has no project checks yet.

**Check:** the human said yes to the task, branch and criteria. Edits they made are applied.

## Gate 2 - Worktree

Find the default branch with `python3 script/github.py default-branch`. Call the `EnterWorktree` tool with `name` set to the branch name. With `worktree.baseRef: fresh` it branches from `origin/<default>` and moves the session into `.claude/worktrees/`, so the main checkout stays clean.

**Check:** `git branch --show-current` prints the new branch, and `git status --short` is empty. `git merge-base HEAD origin/<default>` equals `git rev-parse origin/<default>`.

## Gate 3 - Build and commit each step

Work in small coherent steps. Commit each step as it is finished, not all at the end. Before every commit:

```bash
python3 script/check.py
git add <files>
python3 script/check_conventions.py --staged
```

Fix every `error`. Read every `warning`, and reword the comment unless it truly describes current behavior.

Commit message: Conventional Commits, lowercase, scope optional. The type matches the branch type unless a step is clearly another type.

```
feat(api): add card lookup endpoint
fix: close the pool when startup fails
```

Add a body only when the reason is not visible in the diff. Add no trailers.

**Check:** both scripts pass, the tree is clean, and each subject describes the whole of its commit.

## Gate 4 - Evidence

Run the command of every `runnable` criterion. Keep the command and the last lines of its output as evidence. If gate 1 said the change touches a runnable app or UI, run `/verify` and keep its outcome. Otherwise record `/verify: skipped, no runnable app affected`.

For a web UI change, also drive the page with the `playwright-cli` skill against the local dev server:
- Take a `snapshot` of each listed page and state.
- Take a `screenshot` of each, with `resize` for mobile width, saved with `--filename=.playwright-cli/evidence/<page>-<state>-<width>.png`.
- Walk the changed user flow once: click, fill, submit.
- Check `console` for errors.

Keep the screenshot paths, the flow result and any console errors as evidence. Only local and test environments may be driven freely. On any other site, stop and ask before logging in or submitting data.

A failing criterion sends you back to gate 3.

**Check:** every runnable criterion has passing evidence.

## Gate 5 - Review (fresh context)

Dispatch the `code-reviewer` agent with:
- the base ref `origin/<default>` and the branch name;
- the task;
- the criteria with their tags;
- the evidence from gate 4, including screenshot paths for UI criteria, since the reviewer can read images.

Do not add your own opinion of the code.

- `VERDICT: PASS` opens gate 6.
- `VERDICT: FAIL`: fix each blocking finding in gate 3, redo gate 4 for affected criteria, and dispatch a fresh reviewer.
- A second FAIL stops the flow. Hand the findings to the human, and continue only as they direct.

Minor findings are fixed or listed in the PR body with a reason.

**Check:** the latest verdict is PASS.

## Gate 6 - PR (human in the loop)

Draft the PR in a scratch file, filling every section of `.github/PULL_REQUEST_TEMPLATE.md`:
- **Summary** covers what changed and why.
- **Changes** lists the commits as bullets.
- **Review** gives the verdict, each finding and how it was resolved.
- **Verification** lists each criterion with its command and result, plus the `/verify` outcome and the browser check results. Screenshots stay local unless the human attaches them on GitHub.
- **Docs** says `Pending human review` at this point.
- **Merge checklist** is left unticked.

End the body with the line `Generated with Claude Code`.

Title is the lead commit subject. Show the human the title and body, then wait for yes. On yes:

```bash
python3 script/github.py push
python3 script/github.py pr-create --title "<title>" --body-file <scratch-file>
```

If the push fails with a missing token, stop and point the human to `docs/setup.md`.

**Check:** `python3 script/github.py pr-view` shows an open PR against the default branch whose head SHA equals `git rev-parse HEAD`.

## Gate 7 - CI

```bash
python3 script/github.py pr-checks --wait --timeout 900
```

- Exit 0, `success` or `none`: report and continue.
- Exit 1, `failure`: read the failing check, fix in gate 3, and review again in gate 5 if the fix changes behavior. Then ask the human before pushing again.
- Exit 2, still pending at timeout: report and ask the human whether to keep waiting.
- Exit 3, error: report it, since the credentials or the API failed and CI state is unknown.

**Check:** the checks are green or absent, and that is reported.

## Gate 8 - Docs (human judges)

Decide which files under `docs/` the change affects, using the routing table in CLAUDE.md. Draft the edits in the worktree without committing. Show the human the diff. Knowledge goes in `docs/` only. Describe the current state, not the history of the change.

- **Approve or edit:** apply the human's edits, then commit as `docs(<scope>): ...` after the gate 3 scripts pass. The approval covers this push and the PR body update:

  ```bash
  python3 script/github.py push
  ```

  Then update the PR body's Docs section to list the touched files with `python3 script/github.py pr-edit`.
- **Reject:** discard the draft and set the Docs section to `No docs changes needed` with `pr-edit`. The rejection covers that PR body update.

The reviewer is not re-run for docs. The human's judgment is the review.

**Check:** the PR body's Docs section matches what landed on the branch.

## Gate 9 - Hand off

Report the following:
- the PR URL;
- the review verdict;
- the CI result;
- the docs outcome;
- any open minor findings.

Tell the human that merging is theirs on GitHub, and that they should run `/land` after the merge to clean up. Stay in the worktree.

**Check:** the report is sent, and nothing was merged.
