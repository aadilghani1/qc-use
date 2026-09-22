# Contributing to qc-use

Thank you for your help. This page tells you how to set up the project, how to check your change, how to write commits, and how we review pull requests.

Please follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

```bash
git clone https://github.com/aadilghani1/qc-use.git
cd qc-use
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
```

The hooks run on each commit. They fix lint and formatting with ruff, check whitespace and config files, stop private keys, and check your commit message.

## Check your change

[AGENTS.md](AGENTS.md) holds the code map, the rules, the patterns, and the checks. They apply to people and to coding agents. Its "Done means" section lists the commands to run before a pull request. CI runs the same commands.

The tests run offline. They do not start Chrome, and they do not call any paid API.

To test with a real browser and real models, put `AI_GATEWAY_API_KEY` in `.env` and run:

```bash
uv run --env-file .env qc-use demo --headless
```

The demo costs less than $0.001. It exits with code 0 when the pass, the fail, and the stop for approval all happen as expected.

[CONTEXT.md](CONTEXT.md) defines the words that we use. Please use the same words in code, docs, and messages.

## Commits

We use [Conventional Commits](https://www.conventionalcommits.org/). The commit-msg hook checks the format.

```text
<type>(<optional scope>): <what the commit does, in the imperative>

<optional body: why, and how you checked it>
```

| Type | Use it for |
| --- | --- |
| `feat` | A new behavior that users see. |
| `fix` | A bug fix. |
| `docs` | Documentation only. |
| `test` | Tests only. |
| `refactor` | A code change with no behavior change. |
| `perf` | A faster or cheaper run. |
| `style` | Formatting only. |
| `build` | Packaging, dependencies, and tooling. |
| `ci` | GitHub Actions and Dependabot. |
| `chore` | Other maintenance. |

Use the module name as the scope when it helps: `engine`, `cli`, `runner`, `guards`, `judge`, `spec`, `report`, `secrets`, `demo`, `watch`, `skill`. For a breaking change, add `!` after the type or scope, and explain the change in a `BREAKING CHANGE:` footer.

Examples:

```text
feat(engine): support same-origin iframes
fix(guards): block links to other ports on the same host
docs: explain exact checks in the README
```

Make each commit atomic: one logical change, and all checks pass at that commit. Put mechanical formatting in its own `style` commit, and add its hash to `.git-blame-ignore-revs`.

## Pull requests

1. Open an issue first for a large change, so that we can agree on the design.
2. Keep one change in one pull request.
3. Add a test for each behavior change.
4. Update the docs that the change touches. The docs table in [AGENTS.md](AGENTS.md#docs) lists them.
5. Write docs in simple English: short sentences, active voice, and the words in `CONTEXT.md`.
6. Give the pull request a Conventional Commits title. We squash-merge, so the title becomes the commit on `main`.
7. Fill in the pull request template: what changed, and how you checked it.

## Good first issues

- Support same-origin iframes in `snapshot.js`.
- Add example test files to `examples/` for common flows, such as sign up or checkout.
- Make error messages clearer.
- Add a GitHub Actions example that runs qc-use against a preview deployment.
