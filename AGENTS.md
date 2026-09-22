# Notes for coding agents

Read README.md and CONTEXT.md before you edit. Use the words from CONTEXT.md.

- Keep the loop small: page, list of elements, operation and target, action, fresh check.
- Jev chooses an operation and a target in one request. Use only the target of the chosen operation.
- A target must map to an observed element. Never let model output become a selector or code.
- Never repeat a browser action. Record an action before you read the page again.
- No secret value reaches a model, a report, a trace, or a screenshot.
- A step passes only when its checks pass on a fresh read of the page.
- Tests must not call paid APIs.
- Keep `.env` and `qa/.env` out of git.
- Do not commit or push unless the user asks.

Checks: `uv run ruff check .`, `uv run pytest`, `node --check qc_use/engine/snapshot.js`, `uv build`.
