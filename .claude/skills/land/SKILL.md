---
name: land
description: "Clean up after a human merged a /ship PR: sync the default branch, remove the worktree, delete the local and remote branch. Confirms the merge first and asks once before deleting."
argument-hint: "Branch or PR number (defaults to the current worktree's branch)"
disable-model-invocation: true
---

# Land

This skill runs after the human has merged the PR on GitHub. It never merges.

The Human in the loop rule from CLAUDE.md applies. Every deletion is listed first, and one explicit yes covers the whole list. All GitHub access goes through `python3 script/github.py`.

## Step 1 - Confirm the merge

Identify the branch and its PR. Use the argument if one was given, otherwise the current worktree's branch.

```bash
git worktree list
python3 script/github.py pr-merged --branch <branch>   # or --number N
```

If the PR is not merged, stop and say so. Nothing is deleted for an unmerged PR.

**Check:** `pr-merged` printed `true` and exited 0. Exit 1 means not merged, and exit 3 means an error to report.

## Step 2 - Find stale worktrees

List every other worktree under `.claude/worktrees/`. For each one, run `python3 script/github.py pr-merged --branch <its branch>`. Collect the ones whose PR is merged, so they can be offered in the same confirmation.

**Check:** each worktree is classified as merged, open or without a PR.

## Step 3 - Plan (human in the loop)

Show one list, then wait for yes:
- The main checkout path to sync.
- Each worktree path to remove.
- Each local branch to delete.
- Each remote branch to delete, marked `already gone` when GitHub auto-deleted it.
- The merged stale worktrees from step 2, which the human may include or leave out.

If a worktree has uncommitted changes or commits missing from the merged PR, show them. Leave that worktree out unless the human explicitly includes it.

**Check:** the human said yes and named any exclusions.

## Step 4 - Execute

For each approved branch:

1. Leave the worktree first. If this session entered it with `EnterWorktree`, call `ExitWorktree` with `action: "keep"`. Otherwise work from the main checkout.
2. Sync the default branch in the main checkout:
   ```bash
   python3 script/github.py sync --path <main-checkout>
   ```
3. Remove the worktree and the local branch:
   ```bash
   git -C <main-checkout> worktree remove <worktree-path>
   git -C <main-checkout> branch -d <branch>
   ```
   If `-d` refuses because the PR was squash- or rebase-merged, use `-D`. Step 1 already confirmed the merge through the API.
4. Delete the remote branch:
   ```bash
   python3 script/github.py branch-delete --branch <branch>
   ```

**Check:** `git worktree list` no longer shows the removed paths, and `git branch --list <branch>` is empty. The default branch in the main checkout contains the merged work.

## Step 5 - Report

List what was removed, what was left and why, and the default branch's new head commit.
