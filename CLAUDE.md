@AGENTS.md

## Claude Code

- Add `--headless` to `qc-use run` and `qc-use demo` for live checks, so that no Chrome window opens on the user's screen.
- With `--watch`, set `BROWSER=true` so that the live view stays out of the user's browser.
- qc-use starts its own Chrome. Test qc-use with qc-use. The browser-harness skill drives the user's own Chrome, for other tasks.
- Write run output to the scratchpad: `--results <scratchpad>/qa-results`.
- `.env` holds a real AI Gateway key. Load it with `uv run --env-file .env`, and keep its value out of commands and output.

## Branches and contributions

Follow the Git rules in [AGENTS.md](AGENTS.md#git) and the workflow in [CONTRIBUTING.md](CONTRIBUTING.md#branches-and-forks).

- Create local task branches with names such as `fix/step-completion` or `docs/contribution-workflow`.
- Do not include Claude, Codex, another agent name, or a session identifier in branch names.
- Do not add agent `Co-authored-by` trailers or generated-by signatures to commits or PRs.
- Keep the configured contributor identity and preserve human credit and required upstream attribution.
- Branch creation does not authorize committing, pushing, creating a fork, opening a PR, or merging.
- Honor existing task authorization. Use the fork workflow when upstream write access is unavailable.
