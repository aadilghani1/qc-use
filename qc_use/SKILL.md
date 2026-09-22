---
name: qc-use
description: Critical-path QA for web apps in plain words. Use when the user wants to test, QA, or verify a user flow in a running web app (login, signup, onboarding, checkout, "the critical path"), or to rate how easy a flow is for a persona. Writes a qc-use test file from the user's description, runs it in an isolated Chrome driven by TypeSafe Jev, and explains the step-by-step report.
homepage: https://github.com/aadilghani1/qc-use
---

# qc-use

qc-use runs a plain-language critical path against a web app and reports a verdict for each step. Jev (TypeSafe) chooses every action from the elements actually on the page; it never writes selectors or code. Each step is checked against recorded actions and a fresh page. A model decision to stop does not prove success.

You write the test file, confirm it with the user, run it, and explain the result. You do not drive the browser yourself.

## 1. Check setup

```bash
qc-use doctor
```

It checks Chrome, the inference key, and the text helper. If `AI_GATEWAY_API_KEY` is missing, tell the user to create a Vercel AI Gateway key and put it in `qa/.env` themselves. Never ask them to paste a key or password into the chat. If `qc-use` is not installed, follow https://github.com/aadilghani1/qc-use/blob/main/install.md.

## 2. Write the test from the user's words

Turn the user's description into `qa/<flow-name>.md` (run `qc-use init` first if `qa/` does not exist). Split it into ordered steps. Each step must end in a visible state. Show the steps to the user. Ask the user to confirm or correct them before you run the test.

```md
---
url: http://localhost:3000/login
secrets: [LOGIN_EMAIL, LOGIN_PASSWORD]
persona:
  role: Head of Operations
  company_size: 51-200
never: [cancel the subscription]
rate:
  onboarding_ease: [confusing, effortful, okay, smooth, effortless]
---
# Onboarding critical path

A new operations lead signs in for the first time and finishes onboarding.

1. Sign in with LOGIN_EMAIL and LOGIN_PASSWORD
   - expect: the onboarding welcome screen is showing
2. Complete the profile as the persona and continue
   - expect: the workspace step is showing
3. Create a workspace and finish onboarding
   - expect: the dashboard shows the new workspace
   - check: url contains /dashboard
```

Rules for good tests:

- **Observation steps:** add `- mode: observe` and explicit checks. Never grade reading as an input action.
- **Action evidence:** add `- action: Click Save` when a specific input must be proved. Split ordered inputs into separate steps.
- **One outcome per step.** A step says what to do; `expect:` says what the page shows when it worked. Write expectations the user would accept as proof.
- **Counts, dates, exact values, and URLs go in `check:`** (`url contains X`, `url matches REGEX`, `title contains X`, `text contains X`, `text does not contain X`, `document contains X`). Jev is weak at counting and date comparison.
- **Credentials are names, never values.** List them in `secrets:` and mention the names in steps. The user sets the values in `qa/.env` or the environment. Password fields only ever receive a declared secret.
- **Personas are explicit fields.** Unlisted required fields get clearly fake test values, flagged in the report.
- **Uploads use declared files**: `files: { avatar: fixtures/avatar.png }` (paths relative to the test file).
- **Never-do rules** are plain words (`never: [...]`). Defaults already cover deleting data, payments, and messaging real people. Do not set `never_defaults: false` unless the user asks.
- **Ratings** (`rate:`) are 2–10 levels from worst to best. Add `min:` only if the user wants a low rating to fail the test.
- Only test localhost, staging, or preview URLs. Production-looking URLs are refused unless the user explicitly sets `allow_production: true`.

`qc-use schema test` prints the full test-file schema.

## 3. Run it

```bash
qc-use run qa/<flow-name>.md
```

Add `--watch` only if the user wants to watch the live inspector. Each run uses a fresh Chrome profile unless `--profile` reuses a dedicated profile. Results land in `qa-results/<run-id>/`.
The live view is read-only. A missing image means masking could not be checked.
Use `qc-use demo --watch` for visible Chrome and its inspector. Add `--headless` only when the user wants Chrome hidden.
Viewport text is capped at 6,000 characters. Document text is capped at 20,000 characters.
Use `verify_timeout` for slow result transitions. In-flight checks may finish after this polling window.
`max_model_calls` defaults to 200 HTTP attempts, including retries. Never lower pass thresholds merely to pass a test.
`--repeat` requires `repeat_safe: true` and equivalent server-side fixtures. It does not reset accounts.
For OTP or OAuth, use a dedicated `--profile` with `--manual-auth` in an interactive terminal.
This handoff tests the authenticated continuation, not automated login. Never create more production accounts to work around authentication.
Use `secret_templates` only for explicitly declared `{tag}` values such as staging mailbox aliases.

## 4. Report back

Read `qa-results/<run-id>/report.json`. (`qc-use schema report` prints its schema.) Then answer in plain words:

- Which steps passed.
- Where the run stopped, and why.
- Any signals, such as console errors or HTTP failures.
- Generated test values.
- Ratings, with their confidence, partial coverage, and any `rating_issues`.
- Model retries, pricing source, request count, and the source hash in `models.build`.

| Exit | Outcome | What you do |
| --- | --- | --- |
| 0 | pass | Summarize. Mention ratings and any signals worth a look. |
| 1 | fail | Explain the failing check or `fail_on` signal. It is probably an app bug; show the evidence. |
| 2 | inconclusive / blocked | Explain the reason. Blocked often means an unsupported surface (iframe, OAuth pop-up, email code). Suggest a clearer `expect:` for inconclusive checks. |
| 3 | needs approval | A never-do rule may apply. Ask the user. Only if they agree, rerun with the `approval.rerun_with` command. |
| 4 | setup error | Fix the test file, secret, key, or URL the message names. |

Do not edit a test to make a failure pass without telling the user. Do not retry silently; `--repeat N` exists to measure flakiness honestly.

## Limits

qc-use reports these cases as blocked, with a reason: iframes, OAuth pop-ups, new tabs, email or SMS codes, `prompt()` dialogs, canvas, and shadow DOM. Ratings are Jev's judgment from the run's evidence, not measurements.
