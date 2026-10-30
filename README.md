# Harness Engineering: build a coding agent

A course where you build a coding agent, lesson by lesson, with no agent framework:
the `openai` package is the only thing that talks to the model.

## Setup

```
uv sync
```

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/). Your code goes in `agent/`.
Start with `lessons/00-setup`.

## Running tests

```
uv run pytest                                        # all default tests (no model server needed)
uv run pytest lessons/01-the-loop                    # one lesson, against your agent/
uv run pytest lessons/01-the-loop --impl solutions/01-the-loop   # against a reference solution
uv run pytest --live                                 # also run tests that need a live model server
uv run python scripts/check_solutions.py [--upto NN] # check every solution against every earlier lesson
```

`--impl PATH` picks the directory whose `agent` package the tests import (default: this repo).
Tests marked `sandbox` need a working bubblewrap (`bwrap`) and are skipped without it.

## Lessons

(Index completed at the end of the course build.)
