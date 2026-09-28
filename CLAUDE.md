# CLAUDE.md

## Rules

1. No emoji anywhere: code, comments, docs, commits, PRs.
2. No history in code or comments. Git and PRs hold the history.
3. Code comments only describe what the code does and how it works, as bullet points.
4. Knowledge lives in `docs/`.
5. Scripts live in `script/` and are written in Python 3.10+ using only the standard library.
6. Human in the loop: see below. It binds every skill and every session.
7. Never verify your own work. Reviews go to a fresh-context agent.

## Human in the loop

- Local work runs without asking: reading, editing, running checks, committing, creating worktrees.
- Stop for an explicit yes before anything that leaves the machine: push, PR create or edit, API writes, and logging in or submitting data through a browser on any site that is not local or a test environment.
- Stop for an explicit yes before anything irreversible: deleting files, branches or worktrees, force operations, history rewrites.
- Stop for an explicit yes when a check or review still fails after its retry budget.
- A yes covers only the action it was asked for.
- Merging is always done by the human.

## Commands

```bash
python3 script/check.py                        # project checks, run before every commit
python3 script/check_conventions.py --staged   # rules 1, 2, 4, 5 on staged changes
python3 script/github.py --help                # GitHub API client, credentials in .env.skills
```

Ship changes with `/ship`. Work a GitHub issue with `/issue <number>`. Clean up after a merge with `/land`.

## Docs routing

| When | Read |
| --- | --- |
| Before changing code or finding where something lives | [docs/architecture.md](docs/architecture.md) |
| Running /ship or /land, writing commits, delegating to agents | [docs/workflow.md](docs/workflow.md) |
| Setting up credentials, installing or updating the harness | [docs/setup.md](docs/setup.md) |
| Looking for any other knowledge | [docs/README.md](docs/README.md) |

## Project

Multi-threaded command line downloader for k2s.cc free links, using public proxies and resumable part files.

```bash
uv sync                                                  # install dependencies
uv run main.py dl <url> [--filename F] [--threads N] [--split-size 20mb]
uv run main.py ls                                        # list unfinished downloads
uv run main.py continue [file_id]                        # resume unfinished downloads
python3 script/check.py                                  # harness tests, then py_compile through uv
```

Invariants, detailed in [docs/architecture.md](docs/architecture.md#invariants):
- `urls.json` and `proxies.txt` are only touched under `file_lock`.
- Importing `main.py` fetches proxies over the network. Never import it from checks or tests.
- A part file in `tmp/` holds exactly the bytes downloaded so far for its range, which is what makes resuming work.
