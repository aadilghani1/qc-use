# Install qc-use

This guide is for people and for coding agents. Do the steps in order.

## What you need

- **Chrome.** qc-use starts its own Chrome window with a new, empty profile. It does not touch your everyday Chrome profile.
- **uv.** Install it from [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/). uv installs Python 3.12 for you.
- **A Vercel AI Gateway key.** Create one at [vercel.com/docs/ai-gateway](https://vercel.com/docs/ai-gateway). One key runs Jev and the text helper.

## 1. Install

```bash
uv tool install --python 3.12 --upgrade git+https://github.com/aadilghani1/qc-use
```

Check the install:

```bash
qc-use --version
```

## 2. Register the skill for your coding agent

```bash
qc-use skill install
```

This writes one `SKILL.md` file for each coding agent that it finds: Claude Code, Codex, Cursor, Gemini CLI, Copilot, and opencode. It always writes `~/.agents/skills/qc-use/SKILL.md`. Restart your agent after this step.

To choose one agent, use `qc-use skill install --target claude`. To write the file to one exact place, use `--path`.

## 3. Add your key

In your app's folder, run:

```bash
qc-use init
```

This creates `qa/onboarding.md` (an example test) and `qa/.env`. It also adds `qa/.env` and `qa-results/` to `.gitignore`.

Open `qa/.env` and set your key:

```bash
AI_GATEWAY_API_KEY=your-key
```

You can also set the key in your environment. The environment wins over `qa/.env`. Empty template values do not hide values from the project’s `.env`.
qc-use reads `.env` files as dotenv does. It removes one pair of quotes around a value. `export NAME=value` works. Text after ` #` is a comment, so quote a value that contains ` #`.

Coding agents: do not ask the user to paste a key or a password into the chat. Ask the user to edit `qa/.env`.

## 4. Check the setup

```bash
qc-use doctor
```

To also check a test file, its secrets, and your app, run:

```bash
qc-use doctor qa/onboarding.md
```

`doctor` makes no paid model calls. Add `--json` for structured results and installed skill status.
It checks credentials and setup. A run checks current model availability before starting Chrome.
Run `qc-use validate qa/onboarding.md --json` to check the file without Chrome, secrets, or network access.

After an upgrade, run `qc-use skill status`, then `qc-use skill install` to refresh outdated copies.
Codex installation respects `CODEX_HOME`. opencode installation respects `XDG_CONFIG_HOME`.
These checks verify skill files. Restart your agent to load them.

Run `qc-use report qa-results/<run-id>` to reopen saved evidence. Add `--no-open` to print the URL without opening it.
Keep this command running while viewing the report. Press Ctrl+C to close it.

## 5. Try the demo

```bash
qc-use demo --watch --results /tmp/qc-use-demo
```

The demo starts a small app on port 3100 and runs 3 tests. You see a pass, a fail, and a stop for approval. `qc-use demo` exits with code 0 when all 3 outcomes are as expected.

## Problems and fixes

| Problem | Fix |
| --- | --- |
| `Chrome was not found` | Install Google Chrome. Or set `QC_USE_CHROME` to the path of Chrome or Chromium. |
| `Jev needs AI_GATEWAY_API_KEY` | Set the key in `qa/.env` or in your environment. |
| `AI Gateway rejected the key` | Create a new key. Check that your Vercel team has AI Gateway credit. |
| `Missing secrets: NAME` | Add `NAME=value` to `qa/.env` next to the test file, or to your environment. |
| `looks like a production site` | Use localhost, staging, or a preview URL. Or set `allow_production: true` if you are sure. |
| `The page failed to load` | Start your app. Check the `url` in the test file. |
| Port 3100 is in use (demo) | Stop the other program, or run `qc-use demo --serve --port 3200` to serve the demo app only. |

## Use TypeSafe directly

To call TypeSafe without the gateway, set:

```bash
JEV_PROVIDER=typesafe
TYPESAFE_API_KEY=your-typesafe-key
TEXT_MODEL_API_KEY=your-text-model-key
TEXT_MODEL_BASE_URL=https://openrouter.ai/api/v1
```

`TEXT_MODEL_BASE_URL` uses the OpenAI chat-completions format. The chosen model must support JSON output.
Generic providers receive no reasoning settings by default. Set `TEXT_MODEL_REASONING` only when your provider supports it.
If a provider does not report cost, qc-use stops before another model request.
The gateway key is used only for the exact HTTPS gateway host.

## Uninstall

```bash
uv tool uninstall qc-use
```

Then delete the `SKILL.md` files that `qc-use skill install` listed.

Use `--headless` to hide Chrome. The `--watch` inspector is independent. Do not set `BROWSER=true` when automatic opening is wanted.

Test files, environment files, saved reports, and CLI output use UTF-8 on every platform.
