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

If an expectation does not pass, qc-use waits 1 second, reads the page again, and asks one more time. This helps with pages that finish loading late. qc-use never counts "inconclusive" as a pass.

qc-use also checks the step text against the recorded actions. An already-visible destination does not prove that a requested action occurred.
If a step has no `expect:` line, the report calls its check an `implicit` check.
Observation-only steps can pass without input.

## Exact checks

A `check:` line is a rule that code checks exactly. Use exact checks for URLs, counts, dates, and exact words. Jev is not reliable at counting or comparing dates.

| Check | Example |
| --- | --- |
| `url contains X` | `check: url contains /dashboard` |
| `url matches REGEX` | `check: url matches /orders/\d+$` |
| `title contains X` | `check: title contains Dashboard` |
| `text contains X` | `check: text contains "3 items"` |
| `text does not contain X` | `check: text does not contain Error` |

The text checks look at the visible text of the page. They ignore upper and lower case.

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
