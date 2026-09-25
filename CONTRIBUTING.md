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

## Branches and forks

Use one branch for one change. Keep `main` ready to release.
Name branches `<type>/<short-description>`, using lowercase words and hyphens.
Use the commit types below, such as `fix/step-completion`, `feat/report-export`, or `docs/contribution-workflow`.
Do not include agent names, personal names, session identifiers, random suffixes, or names such as `patch-1`.

Check `git status` before switching branches. Preserve unrelated work.
For a clean checkout with upstream write access:

```bash
git remote -v
git fetch origin
git switch main
git merge --ff-only origin/main
git switch -c fix/step-completion
```

These commands assume `origin` points to `aadilghani1/qc-use`. Verify that first.
Continue an existing task on its existing branch. Use a separate worktree when another task needs an isolated checkout.
Agents may create local branches for authorized work. Creating a branch does not authorize publishing or merging.

### Contribute from a fork

Without upstream write access, fork `aadilghani1/qc-use` on GitHub and clone your fork.
Agents must have user authorization before creating a remote fork or publishing changes.
Set `origin` to your fork and `upstream` to this project:

```bash
git remote -v
git remote add upstream https://github.com/aadilghani1/qc-use.git
git fetch upstream
git switch -c fix/step-completion upstream/main
```

Add `upstream` only if it is absent. Check its URL if it already exists.
After committing and checking the change, push your task branch:

```bash
git push -u origin fix/step-completion
```

Open a PR from your fork's task branch to `aadilghani1/qc-use:main`.
Maintainers with write access use the same branch and PR process within this repository.
Do not push directly to `main`.

### Keep branches clean

Review the final diff and run the required checks before pushing.
Keep unrelated edits, secrets, generated results, and dependency folders out of commits.
Resolve review findings and wait for required CI checks before merging. Use draft PRs for incomplete work.
Do not force-push shared branches. Use `--force-with-lease` only when a task-branch rewrite is explicitly authorized.
After merging, update local `main` with a fast-forward. Delete merged task branches when cleanup is authorized.
Do not delete unmerged branches or rewrite unrelated history.

## Check your change

[AGENTS.md](AGENTS.md) holds the code map, the rules, the patterns, and the checks. They apply to people and to coding agents. Its "Done means" section lists the commands to run before a pull request. CI runs the same commands.

Run `uv run python tools/verify_browser.py` for local Chrome capture and document-text fixtures without model calls.
Run `uv run mypy` to check the Python interfaces. CI checks types as well as the required checks.

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

### Authorship

Use your configured contributor identity. Agents must not invent an author or change Git identity settings.
Do not add agent co-author trailers, generated-by footers, badges, or signatures to commits or PRs.
This includes `Co-authored-by: Claude`, `Co-authored-by: Codex`, and equivalent tool attribution.
Preserve genuine human credit and required upstream copyright, license, and attribution notices.

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

## Tune the live view

The shipped live view is one HTML file with no build step or remote assets.
Use the optional DialKit preview to adjust motion, radius, and color against synthetic data:

```bash
npm ci --prefix tools/preview
python3 tools/preview/serve.py
```

Open `http://127.0.0.1:4318`. Expand the DialKit panel, adjust the controls, and copy the chosen values into `qc_use/watch.html`.
Replay restarts the synthetic run. No model or test account is used.
DialKit is a development tool. It is excluded from the Python wheel.

The interface uses short CSS transitions and honors reduced motion. Evidence disclosures keep their state during live updates.
Design references: [Emil Kowalski](https://animations.dev/), [Shawn](https://www.shwn.design/), and [DialKit](https://www.dialkit.dev/agent).

## Releases

Update the version in `pyproject.toml`, `qc_use/__init__.py`, and `plugins/qc-use/.claude-plugin/plugin.json`, then run `uv lock`.
Update the action version in the README and in `docs/ci.md`. A test fails when these versions disagree.
Run all checks and review the installed wheel before tagging a release.

```bash
uv build
uv venv /tmp/qc-use-install
uv pip install --python /tmp/qc-use-install/bin/python dist/qc_use-*.whl
/tmp/qc-use-install/bin/python tools/check_install.py
```

CI checks installed wheels on Linux, macOS, and Windows. These checks cover CLI setup and skill files, not each agent's runtime.
The Chrome fixture runs on Linux. Maintainers also run the live model demo before engine changes ship.

After review and merge, a maintainer pushes a `v<version>` tag matching the package version.
The release workflow runs the checks and builds once. Then it attaches the wheel and source archive to a GitHub release, and it publishes them to PyPI.
PyPI publishing uses trusted publishing: PyPI trusts `release.yml` in the `pypi` environment, so no token is stored. A failed check prevents publication.
Install a known release with `uv tool install --python 3.12 qc-use==<version>`, or use the action at `aadilghani1/qc-use@v<version>`.
Refresh installed instructions with `qc-use skill install` after upgrading.

## Verify first use outside this checkout

Build and install the current wheel into a temporary environment. Use that environment's Python for this check:

```bash
/path/to/environment/bin/python tools/verify_first_use.py
```

Set a model key in the environment first. The check uses a paid preflight and local demo login.
It creates a separate temporary project, writes a test from the login fixture, and opens visible Chrome and the inspector.
It checks live images, the command result, and reopening saved step evidence. Add `--headless` for unattended verification.
This POSIX check is opt-in. It does not run as an offline unit test or authenticate to a real customer app.

For agent acceptance, start an agent in a fresh app folder and use the README prompt.
Confirm it discovers the start command, uses configured credentials, writes and validates the test, and surfaces the live link before waiting.
Confirm it explains the outcome and provides the saved-report command. Record the agent and installed qc-use version.
The scripted fixture verifies the CLI journey. It does not prove every coding agent follows the skill correctly.
