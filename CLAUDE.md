@AGENTS.md

## Claude Code

- Add `--headless` to `qc-use run` and `qc-use demo` for live checks, so that no Chrome window opens on the user's screen.
- With `--watch`, set `BROWSER=true` so that the live view stays out of the user's browser.
- qc-use starts its own Chrome. Test qc-use with qc-use. The browser-harness skill drives the user's own Chrome, for other tasks.
- Write run output to the scratchpad: `--results <scratchpad>/qa-results`.
- `.env` holds a real AI Gateway key. Load it with `uv run --env-file .env`, and keep its value out of commands and output.
