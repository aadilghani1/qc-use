# Test files

A test file describes one critical path. It is a Markdown file, usually in `qa/`. It has two parts:

1. Settings, in YAML between two `---` lines.
2. A title, an optional short description, and numbered steps.

Run `qc-use init` to create an example. Run `qc-use schema test` to see the full schema.

## A complete example

```md
---
url: http://localhost:3000/login
allow: [auth.localhost:3000]
secrets: [LOGIN_EMAIL, LOGIN_PASSWORD]
files:
  avatar: fixtures/avatar.png
persona:
  name: Priya Raman
  role: Head of Operations
  team_size: 51-200
never: [cancel the subscription]
rate:
  onboarding_ease: [confusing, effortful, okay, smooth, effortless]
fail_on: [js_exception, http_5xx]
---
# Onboarding critical path

A new operations lead signs in for the first time and finishes onboarding.

1. Sign in with LOGIN_EMAIL and LOGIN_PASSWORD
   - expect: the "About you" onboarding step is showing
2. Fill in the profile as the persona, upload the avatar, and continue
   - expect: the workspace step is showing
3. Create a workspace named after the persona's company and finish onboarding
   - expect: the dashboard welcomes Priya
   - check: url contains /dashboard
```

## Settings

Only `url` is required.

| Setting | Default | Meaning |
| --- | --- | --- |
| `url` | required | The page where the test starts. It must be `http` or `https`. |
| `title` | the `#` heading | The name of the test in the report. |
| `allow` | `[]` | More sites that the test can visit. The start site is always allowed. Use `host`, `host:port`, or `*.domain`. |
| `allow_production` | `false` | Set `true` to run against a URL that looks like production. |
| `secrets` | `[]` | Names of private values, such as `LOGIN_PASSWORD`. qc-use reads the values from the environment or from `.env` next to the test file. |
| `files` | `{}` | Files that the test can upload, as `name: path`. Paths are relative to the test file. |
| `persona` | `{}` | Facts about the user that qc-use acts as. The text helper uses them to fill forms. |
| `never` | `[]` | Your never-do rules in plain words, such as `cancel the subscription`. |
| `never_defaults` | `true` | Set `false` to remove the default never-do rules. See [safety.md](safety.md). |
| `never_threshold` | `0.3` | The gate stops an action when the probability that it breaks a rule is this high or higher. |
| `rate` | `{}` | Ratings of the run. Each rating has 2 to 10 levels, from worst to best. |
| `fail_on` | `[]` | Signals that make a step fail: `console_error`, `js_exception`, `http_4xx`, `http_5xx`, `request_failed`. |
| `budget` | `{step: 15, test: 60}` | The maximum number of actions for each step and for the whole test. |
| `bands` | `{pass_at: 0.8, fail_at: 0.2}` | How Jev probabilities become outcomes. See [Expectations](#expectations). |
| `max_cost` | `0.25` | The reported-spend limit before another model request. Unknown pricing stops further calls. |

## Steps

Each numbered line is a step. Write it as an instruction to a person:

- Good: `Fill in the profile as the persona and continue`
- Too big: `Sign up, fill the profile, invite the team, and create the first report`
- Too vague: `Do the onboarding thing`

A long step can continue on the next line. Indent the next line.
A long `expect:` or `action:` can continue the same way. Put each `check:` and `mode:` on one line.

Details (`expect:`, `check:`, `action:`, and `mode:`) belong to the step above them. The list marker (`-`, `*`, or `+`) and the indentation are optional.
After the first step, a line that is not a step, a detail, or an indented continuation is an error. qc-use does not drop it silently.
Save test files as UTF-8. Quote a setting name that YAML reads as a boolean or a number, such as `"on"`.

qc-use runs the steps in order. If a step does not pass, qc-use stops. The later steps get the outcome `skipped`, because they depend on the earlier steps.

## Expectations

An `expect:` line says what the page must show when the step works. Write something that a person can see on the screen:

- Good: `expect: the dashboard shows the Northwind Freight workspace`
- Bad: `expect: the database saved the record` (the page cannot show this)

After the step, qc-use reads the page again. Jev answers a yes-or-no question for each expectation and gives a probability:

| Probability | Outcome |
| --- | --- |
| 0.8 or more | pass |
| 0.2 or less | fail |
| between 0.2 and 0.8 | inconclusive |

If checks do not pass, qc-use rereads the page until `verify_timeout` expires. The default is eight seconds.
An in-flight check may finish after this polling window. Only reads and model questions repeat. Browser input does not repeat. An inconclusive check never becomes a pass by timeout.

An action step requires recorded input. Use `action:` to require a specific action, verified against this step's history.
With explicit `expect:` or `check:` lines, the prose instruction is not an extra hidden expectation.
With no declared outcomes or actions, qc-use uses the instruction as an `implicit` check.

An observation step uses `mode: observe`. It runs checks without asking Jev to act.
It requires an `expect:` or `check:` and cannot contain `action:`.

```md
1. Read the hero section
   - mode: observe
   - check: text contains Your agent froze
2. Reject cookies
   - action: Click Reject All
   - expect: the cookie banner is closed
3. Open signup
   - action: Click Start free
   - check: text contains Create your agent account
```

Put ordered actions in separate steps. Do not combine cookie handling, navigation, and waiting into one instruction.
Do not duplicate an exact fact as a model expectation. Reserve `expect:` for facts that need semantic judgment.

## Exact checks

A `check:` line is a rule that code checks exactly. Use exact checks for URLs, counts, dates, and exact words. Jev is not reliable at counting or comparing dates.

| Check | Example |
| --- | --- |
| `url contains X` | `check: url contains /dashboard` |
| `url matches REGEX` | `check: url matches /orders/\d+$` |
| `title contains X` | `check: title contains Dashboard` |
| `text contains X` | `check: text contains "3 items"` |
| `text does not contain X` | `check: text does not contain Error` |

`text` checks use the current viewport, capped at 6,000 characters. Off-screen content is not included.
`document contains X` checks rendered document text, including off-screen content, capped at 20,000 characters.
Neither scope enters frames or shadow roots. Text comparisons ignore case.
An absence check on truncated text is unavailable, rather than a false proof that text is missing.

## Secrets

List secret names in `secrets:`. Use the names in your steps:

```md
secrets: [LOGIN_EMAIL, LOGIN_PASSWORD]
...
1. Sign in with LOGIN_EMAIL and LOGIN_PASSWORD
```

Put the values in `qa/.env` or in your environment:

```bash
LOGIN_EMAIL=qa@example.test
LOGIN_PASSWORD=a-test-password
```

Jev sees only the names. It chooses which secret goes into which field. Code types the value. A password field accepts secrets only. The text helper never gets a password field.

## Personas

A persona is a list of facts:

```yaml
persona:
  name: Priya Raman
  role: Head of Operations
  team_size: 51-200
  company: Northwind Freight
```

The text helper uses these facts to fill forms. Sometimes a form needs a value that the persona does not give. Then the text helper uses a clearly fake test value, such as `qa+ab12cd@example.test` or `555-0142`. The report lists every fake value. The text helper never invents a credential, a verification code, or payment details. For these, the step is blocked.

## Files

Declare the files that the test can upload:

```yaml
files:
  avatar: fixtures/avatar.png
```

Then mention the file in a step: `Upload the avatar`. qc-use offers only declared files. Jev chooses the file by name. Code gives the path to Chrome.

## Ratings

A rating is Jev's score for the whole run. Give 2 to 10 levels, from worst to best:

```yaml
rate:
  onboarding_ease: [confusing, effortful, okay, smooth, effortless]
```

Jev uses the evidence of the run: the number of actions, waits, repeated decisions, dialogs, signals, and the time of each step. The report shows the most likely level, the probability of each level, and Jev's confidence.

A rating does not change the outcome, unless you set a minimum:

```yaml
rate:
  onboarding_ease:
    levels: [confusing, effortful, okay, smooth, effortless]
    min: okay
```

Now the test fails if the most likely level is below `okay`.
If this required rating cannot be checked, an otherwise passing run becomes inconclusive. Optional ratings may be unavailable without changing the outcome.

## Tips

- Write one outcome per step. A step with a clear end is easy to check.
- Use the persona for form values. Do not put real personal data in a test file.
- Use test accounts only. qc-use really clicks the buttons.
- Keep secrets out of step text. Use the secret's name.
- Start with `qc-use run --watch` to see what Jev sees.

## Waiting, repeat runs, and test accounts

Settings:

| Setting | Default | Purpose |
| --- | --- | --- |
| `verify_timeout` | `8` | Polling window in seconds, from 0 to 120. In-flight checks may finish later. |
| `max_model_calls` | `200` | Maximum HTTP model attempts, including retries. |
| `repeat_safe` | `false` | Required for `--repeat N` when N exceeds one. |
| `secret_templates` | `[]` | Declared secret names whose `{tag}` placeholder expands per run. |

`repeat_safe: true` declares that each run has equivalent account state. It does not reset the app or create fixtures.
Use staging accounts or an existing disposable fixture workflow. Do not repeat production signup to measure reliability.
Fresh browser profiles reset browser state, not server accounts. `--profile` reuses browser state too.

For a staging signup mailbox, set `SIGNUP_EMAIL=qa+{tag}@example.test` in the ignored environment file.
Declare `secrets: [SIGNUP_EMAIL]` and `secret_templates: [SIGNUP_EMAIL]`.
Only declared templates expand. Passwords remain literal unless explicitly declared as templates.
The expanded value is redacted like every other secret. Aliases must be supported by your staging authentication system.

For email codes or OAuth, use manual authentication before an authenticated continuation test:

```bash
qc-use run qa/after-login.md --profile /tmp/qc-use-test-profile --manual-auth --watch
```

This requires an interactive terminal and visible Chrome. Sign in yourself, then press Enter in the terminal.
Use a dedicated test profile. Do not use your everyday Chrome profile.
The automated checks start after this handoff; the report does not prove automated signup or login.
`mode: observe` can verify the initial authenticated state before later action steps.

## Rating and cost evidence

Unavailable ratings appear in `rating_issues`, including redacted rejected answers where available.
Valid sibling ratings remain available. Required rating failures make otherwise passing runs inconclusive.
Ratings show partial coverage and low confidence. Their input includes redacted observed content and check results.
These are model judgments, not user research or measured conversion intent.

The report preserves numeric cost precision and lists provider, estimated, reported-zero, and unavailable pricing evidence.
`trace.json` records model attempts, status, retry delay, timing, token usage, and cost evidence.
HTTP 429, 502, 503, 504, 529, and connection failures retry within a 45-second deadline per model request.
Backoff increases from 0.5 to eight seconds with jitter. `Retry-After` takes precedence.
If the requested wait exceeds the remaining deadline, qc-use stops instead of retrying early.
`max_model_calls` counts every attempt, including preflight. Model retries never repeat browser input.
A stalled request can continue at the provider after qc-use stops waiting. Its price remains unknown; its answer cannot cause input.

Before Chrome starts, preflight asks Jev a small question and validates the answer. It uses the configured provider and counts toward limits.
Preflight checks current availability. It cannot guarantee that later calls succeed, and its cost is not assumed to be zero.
After the retry deadline, the run stops further model requests, including ratings.
`provider_issue.kind` is `provider_unavailable`; the run remains blocked with exit code 2 unless application evidence determines another outcome.
The report preserves completed steps, actions, and screenshots. Do not rerun a signup without checking existing account state.
Trace records include purpose, HTTP status, available provider error fields, and request IDs. Credentials and declared secrets are redacted.
Retries never replay browser actions. The request cap remains active when reported cost is zero.
The spend cap uses provider-reported or estimated cost; it is not a prepaid ceiling or proof of eventual billing.

Reports use `qc-use.report/2`. Checks distinguish `action`, `expect`, `implicit`, `check`, and `signal` evidence.
`models.build` is a hash of installed runtime source, so equal package versions can still be distinguished.

Connection failures before sending can retry. Lost responses or partial writes stop immediately with unknown pricing.

## Validate before running

Run `qc-use validate qa/*.md --json` to check syntax and declared files offline.
Validation does not check credentials, app routes, model access, or account state.
Use `qc-use doctor qa/flow.md --json` for setup checks.

## Browser Back and Reload

Use separate steps for native browser navigation:

```md
1. Reload the page
   - action: Reload the page
   - expect: the saved display name is still present
2. Go back in browser history
   - action: Go back in browser history
   - check: url contains /dashboard
```

Back requires a previous HTTP(S) history entry. These actions remain subject to allowed sites and never-do rules.
Adapt the expected route to your actual history. Reload can repeat an app request, so use a disposable test fixture.
