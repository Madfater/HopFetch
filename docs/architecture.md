# Architecture

Navigation map of the codebase. When this file and the code disagree, the code wins, so fix this file.

## Overview

Describe in two or three sentences what the system does and how its parts fit together.

## Layout

| Path | Responsibility |
| --- | --- |
| `script/` | Harness scripts: checks, GitHub client, apply |
| `docs/` | Knowledge |

## Data flow

Describe the main path a request or job takes through the code.

## Invariants

List the rules the code relies on that are not enforced by types or tests.
