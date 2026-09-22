# Contributing to qc-use

Thank you for your help. This page tells you how to set up the project, how to check your change, and what we look for in a pull request.

## Set up

```bash
git clone https://github.com/aadilghani1/qc-use.git
cd qc-use
uv sync
```

## Check your change

Run these commands before you open a pull request:

```bash
uv run ruff check .
uv run pytest
node --check qc_use/engine/snapshot.js
uv build
```

The tests run offline. They do not start Chrome, and they do not call any paid API.

To test with a real browser and real models, put `AI_GATEWAY_API_KEY` in `.env` and run:

```bash
uv run --env-file .env qc-use demo
```

The demo costs less than $0.001.

## Where things are

| Path | What it does |
| --- | --- |
| `qc_use/cli.py` | The `qc-use` command. |
| `qc_use/spec.py` | Reads and checks test files. |
| `qc_use/runner.py` | Runs a test file step by step and writes the report. |
| `qc_use/judge.py` | Jev questions for checks, the gate, dialogs, and ratings. |
| `qc_use/guards.py` | Allowed sites, production URLs, never-do rules, and dialogs. |
| `qc_use/secrets.py` | Reads secrets and hides their values. |
| `qc_use/report.py` | The report format and `report.md`. |
| `qc_use/engine/` | The browser engine: page reading, Jev decisions, and actions. Adapted from jev-ultrafast. |
| `qc_use/demo/` | The Beacon demo app and its 3 tests. |
| `qc_use/SKILL.md` | The skill that coding agents read. |
| `tests/` | Offline tests. |

[CONTEXT.md](CONTEXT.md) defines the words that we use. Please use the same words in code, docs, and messages.

## Rules

These rules keep qc-use safe and easy to trust:

- **Jev chooses from observed elements only.** No model output becomes a selector, a coordinate, or code.
- **Never repeat a browser action.** If an action is uncertain, stop the step and report it.
- **Record an action before you read the page again.**
- **No secret value reaches a model, a report, or a screenshot.**
- **A step passes only on evidence.** "Done" from Jev is not proof. The checks decide.
- **Tests do not call paid APIs.**
- **Keep it small.** Add a new module only when an existing one cannot hold the change.

## Pull requests

- Keep one change in one pull request.
- Add a test for each behavior change.
- Write docs in simple English. Use short sentences and active voice. Use the words in `CONTEXT.md`.
- Describe what you changed and how you checked it.

## Good first issues

- Support same-origin iframes in `snapshot.js`.
- Add example test files to `examples/` for common flows, such as sign up or checkout.
- Make error messages clearer.
- Add a GitHub Actions example that runs qc-use against a preview deployment.
