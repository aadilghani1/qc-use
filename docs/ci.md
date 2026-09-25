# Run qc-use in CI

qc-use runs in any CI system that has Chrome and uv. For GitHub Actions, use the qc-use action. It installs qc-use, runs your test files in headless Chrome, and writes the results in three places:

- The job summary: one row for each test, with the outcome, the steps that passed, the time, and the cost.
- JUnit XML: one test case for each step. Most CI systems show it as test results.
- An artifact: the `qa-results/` folder, with `report.md`, `report.json`, `trace.json`, and the step screenshots.

The job fails when a test does not pass. GitHub then notifies you, as it does for any failed workflow.

## Add the workflow

Put your key and your test secrets in the repository secrets (**Settings → Secrets and variables → Actions**). Then add `.github/workflows/qa.yml`:

```yaml
name: critical paths

on:
  pull_request:
  schedule:
    - cron: "0 * * * *" # every hour
  workflow_dispatch:

jobs:
  qa:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: aadilghani1/qc-use@v0.4.0
        env:
          AI_GATEWAY_API_KEY: ${{ secrets.AI_GATEWAY_API_KEY }}
          LOGIN_EMAIL: ${{ secrets.LOGIN_EMAIL }}
          LOGIN_PASSWORD: ${{ secrets.LOGIN_PASSWORD }}
        with:
          tests: qa/*.md
          base-url: https://staging.example.com
```

The action ref pins the qc-use version. The action installs qc-use from the same ref.

| Input | Default | Meaning |
| --- | --- | --- |
| `tests` | `qa/*.md` | Test files or glob patterns, separated by spaces. |
| `base-url` | none | Start each test on this origin instead. Each test keeps the path from its `url`. |
| `results` | `qa-results` | The folder for run results. |
| `args` | none | More arguments for `qc-use run`, such as `--repeat 3`. |
| `upload` | `true` | Upload the results folder as an artifact. |
| `artifact-name` | `qc-use-results` | The artifact name. Give each job in a matrix its own name. |

The action has two outputs: `exit-code` (see the exit codes in the README) and `junit` (the path of the JUnit file).

## Choose what to test

**A staging or preview site.** Set `base-url` to the site. qc-use refuses a URL that looks like production. A generated preview address, such as `my-app-git-fix-team.vercel.app`, looks like production to qc-use. Add `args: --allow-production` only when the site is a preview with test data.

**The app in the same job.** Start the app before the action, and wait until it answers:

```yaml
      - run: npm ci && npm run build
      - run: npm start &
      - run: npx wait-on http://localhost:3000
      - uses: aadilghani1/qc-use@v0.4.0
        env:
          AI_GATEWAY_API_KEY: ${{ secrets.AI_GATEWAY_API_KEY }}
```

## Run tests in parallel

qc-use runs the test files of one command one after the other. To run them at the same time, use a matrix. Each job gets its own runner and its own Chrome:

```yaml
jobs:
  qa:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        test: [qa/onboarding.md, qa/checkout.md, qa/settings.md]
    steps:
      - uses: actions/checkout@v7
      - uses: aadilghani1/qc-use@v0.4.0
        env:
          AI_GATEWAY_API_KEY: ${{ secrets.AI_GATEWAY_API_KEY }}
        with:
          tests: ${{ matrix.test }}
          artifact-name: qc-use-results-${{ strategy.job-index }}
```

## Schedules and notifications

A `schedule` trigger runs your critical paths at fixed times, such as every hour against staging. GitHub keeps the history of each run with its summary and artifacts.
GitHub sends an email when a scheduled workflow fails. To post to Slack or another service, add a step with `if: failure()` after the action.

Each scheduled run uses real model calls. The cost of each test is in the job summary. Use `max_cost` in a test file to cap it.

## Other CI systems

Install qc-use with uv, then run it with the CI flags:

```bash
uv tool install --python 3.12 qc-use
qc-use run qa/*.md --headless --junit qa-results/junit.xml --summary qa-results/summary.md
```

| Flag | Meaning |
| --- | --- |
| `--headless` | Run Chrome without a window. CI machines have no display. |
| `--base-url URL` | Start each test on this origin instead, such as a preview deployment. |
| `--junit FILE` | Write JUnit XML with one test case for each step. |
| `--summary FILE` | Append a Markdown table with one row for each run. |

In JUnit, a failed step is a `failure`. An inconclusive, blocked, or needs-approval step is an `error`, because the app may not have a bug. A skipped step is `skipped`.
A test file that did not run has one `setup` test case with an error.
The JUnit file and the summary pass through the same redaction as the reports. They never contain a secret value.

## Command results for agents

Use `qc-use run 'qa/*.md' --json-result` for a stable command response:

```json
{
  "schema_version": "qc-use.command/1",
  "reports": [],
  "setup_errors": [{"file": "qa/login.md", "error": "Missing secrets: LOGIN_EMAIL"}],
  "exit_code": 4
}
```

`reports` contains unchanged `qc-use.report/2` objects. `setup_errors` names each test that could not start.
A batch can contain both reports and setup errors. Exit codes retain their existing meanings.
Use `qc-use schema command` to inspect the schema. Existing `--json` behavior is unchanged.
Quoted patterns expand in both `run` and `validate`. Matches are sorted and overlapping paths run once.
An unmatched pattern produces a setup error. Other matched tests still run.
Live URLs appear on stderr with `--watch`. Do not use `--keep-open` in unattended jobs.
