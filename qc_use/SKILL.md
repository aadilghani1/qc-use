---
name: qc-use
description: Critical-path QA for web apps in plain words. Use when the user wants to test, QA, or verify a user flow in a running web app (login, signup, onboarding, checkout, "the critical path"), or to rate how easy a flow is for a persona. Writes a qc-use test file from the user's description, runs it in an isolated Chrome driven by TypeSafe Jev, and explains the step-by-step report.
homepage: https://github.com/aadilghani1/qc-use
---

# qc-use

qc-use runs a plain-language critical path against a web app and reports a verdict for each step. Jev (TypeSafe) chooses every action from the elements actually on the page; it never writes selectors or code. Each step is checked against recorded actions and a fresh page. A model decision to stop does not prove success.

You inspect the project, write the test file, run it within the authorized scope, and explain the result. You do not drive the browser yourself.

## 1. Discover the app and check setup

Inspect the project's agent instructions, README, package scripts, routes, and existing test fixtures.
Find the local start command, target URL, authentication method, and existing test account.
Use configured secret names. Never print credential values or ask for them in chat.
Start the development server when local execution is authorized. Reuse an existing healthy server.
Wait until the actual start URL responds. Do not guess the port or invent routes.

If qc-use is missing, follow https://github.com/aadilghani1/qc-use/blob/main/install.md.
Run `qc-use --version` and `qc-use skill status`. Refresh stale skill copies with `qc-use skill install`.
Run `qc-use doctor --json` for structured setup checks. A successful doctor does not prove model availability.
If a key is missing, ask the user to edit `qa/.env` locally. Existing environment credentials take precedence.

Before testing, distinguish existing-account login from new-account signup. Confirm any unknown account state or destructive boundary.
For OTP or OAuth, prepare authenticated continuation with a dedicated profile and `--manual-auth` in an interactive terminal.
If no interactive terminal is available, give the user the exact local command. Never work around login by creating another account.

## 2. Write and validate the test

Turn the requested critical path into `qa/<flow-name>.md`. Run `qc-use init` if the folder does not exist.
Use observed app labels and routes from project code or existing tests. Mark unknown assertions for clarification instead of guessing.
Split ordered inputs into separate steps. Choose explicit `action:` requirements and exact `check:` assertions where possible.
Use `mode: observe` for reading. Use secret-aware expectations, never literal credential values.
Only include optional branches when the starting fixture makes them deterministic.
Show the generated steps. Proceed when running this local flow is already authorized; ask only for missing decisions or authorization.
Run `qc-use validate qa/<flow-name>.md --json`, then `qc-use doctor qa/<flow-name>.md --json`.

```md
---
url: http://localhost:3000/login
secrets: [LOGIN_EMAIL, LOGIN_PASSWORD]
---
# Sign in

Adapt the labels and expected route to your app. Use an existing test account.

1. Enter LOGIN_EMAIL in the email field
   - action: Enter LOGIN_EMAIL in the email field
   - expect: the email field holds the LOGIN_EMAIL secret
2. Enter LOGIN_PASSWORD in the password field
   - action: Enter LOGIN_PASSWORD in the password field
   - expect: the password field is filled
3. Submit the sign-in form
   - action: Submit the sign-in form
   - check: url contains /dashboard
4. Check the dashboard
   - mode: observe
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
qc-use run qa/<flow-name>.md --watch
```

For a local interactive run, use `--watch` and open the printed URL. Omit it for unattended CI.
For CI, use `qc-use run qa/*.md --headless --junit qa-results/junit.xml --summary "$GITHUB_STEP_SUMMARY"`, or the GitHub Action in https://github.com/aadilghani1/qc-use/blob/main/docs/ci.md.
Use `--base-url` to run the same test on a staging or preview origin. Each run uses a fresh Chrome profile unless `--profile` reuses a dedicated profile. Results land in `qa-results/<run-id>/`.
The live view is read-only. A missing image means masking could not be checked.
Use `qc-use demo --watch` for visible Chrome and its inspector. Add `--headless` only when the user wants Chrome hidden.
Viewport text is capped at 6,000 characters. Document text is capped at 20,000 characters.
Use `verify_timeout` for slow result transitions. In-flight checks may finish after this polling window.
`max_model_calls` defaults to 200 HTTP attempts, including retries and preflight.
Preflight validates Jev before Chrome starts. Provider retries have a 45-second deadline; they never repeat browser input.
If `provider_issue.kind` is `provider_unavailable`, report the outage separately from app bugs. Inspect account state before rerunning. Never lower pass thresholds merely to pass a test.
`--repeat` requires `repeat_safe: true` and equivalent server-side fixtures. It does not reset accounts.
For OTP or OAuth, use a dedicated `--profile` with `--manual-auth` in an interactive terminal.
This handoff tests the authenticated continuation, not automated login. Never create more production accounts to work around authentication.
Use `secret_templates` only for explicitly declared `{tag}` values such as staging mailbox aliases.

Use `action: Reload the page` or `action: Go back in browser history` to verify persistence or browser navigation.
Back is offered only for an observed HTTP(S) history entry. Both operations remain subject to the gate and allowed sites.

## 4. Report back

Read `qa-results/<run-id>/report.json`. Use `qc-use report qa-results/<run-id>` to reopen saved screenshots and evidence. (`qc-use schema report` prints its schema.) Then answer in plain words:

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
