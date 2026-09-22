# Contributing to qc-use

Thank you for your help. This page tells you how to set up the project, how to check your change, and what we look for in a pull request.

## Set up

```bash
git clone https://github.com/aadilghani1/qc-use.git
cd qc-use
uv sync
```

## Check your change

[AGENTS.md](AGENTS.md) holds the code map, the rules, the patterns, and the checks. They apply to people and to coding agents. Its "Done means" section lists the commands to run before a pull request.

The tests run offline. They do not start Chrome, and they do not call any paid API.

To test with a real browser and real models, put `AI_GATEWAY_API_KEY` in `.env` and run:

```bash
uv run --env-file .env qc-use demo
```

The demo costs less than $0.001.

[CONTEXT.md](CONTEXT.md) defines the words that we use. Please use the same words in code, docs, and messages.

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
