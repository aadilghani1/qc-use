## What changed

<!-- One logical change. Say what a user or a report sees differently. -->

## How I checked it

<!-- Commands you ran and what they showed. Say if you ran the live demo. -->

## Checklist

- [ ] The title follows Conventional Commits, for example `fix(guards): ...`.
- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, `node --check qc_use/engine/snapshot.js`, and `uv build` pass.
- [ ] Each behavior change has an offline test.
- [ ] The docs that this change touches are updated (see the docs table in AGENTS.md).
- [ ] For a change to the runner, guards, judge, or engine: `uv run --env-file .env qc-use demo --headless` exits 0.
- [ ] No secret, key, or private URL is in the diff.
