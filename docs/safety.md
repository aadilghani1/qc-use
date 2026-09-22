# Safety

qc-use really clicks buttons in a real browser. This page tells you what qc-use does to keep your data and your accounts safe, and what it does not do.

**The short version:** use a test account and test data. qc-use has several guards, but no guard is perfect.

## What leaves your machine

qc-use sends these things to Jev (through Vercel AI Gateway or TypeSafe):

- The visible text of the page, up to 6,000 characters.
- The list of elements on the page: their labels, roles, and values.
- The step, the persona, and the names of the secrets.

qc-use sends these things to the text helper:

- The step, the persona, and the text field that needs a value.
- The visible text of the page.

qc-use does **not** send:

- Secret values. qc-use replaces each secret value with `[secret:NAME]` before every request.
- Screenshots. No model sees an image.
- Password field values. The page reader reports only if a password field is filled.

## Secrets

CLI headers, setup errors, and repeat summaries also mask declared secrets after loading the test environment.

- A test file contains secret names only.
- qc-use reads the values from your environment first, then from `.env` next to the test file.
- Jev chooses which secret goes into which field. Code types the value.
- A password field accepts secrets only.
- qc-use hides secret values in `report.md`, `report.json`, `trace.json`, and step screenshots. For screenshots, qc-use checks the page before and after a new capture and masks matching text and form values.
  It omits changed pages and unsupported secret surfaces, including frames, images, canvas, video, custom elements, and generated CSS content.
  Cached images are never masked against a later page.
  Exact matching cannot recognize transformed values or malicious page behavior. This is not protection against a hostile app.

Secrets with fewer than four characters are refused before Chrome starts. They cannot be distinguished safely from ordinary text.
Field names and outcome labels are code-owned values and are not rewritten during redaction.

Each test loads its own environment files. A previous test file cannot supply credentials to the next test.

Secrets can target any editable field. Jev chooses the field; qc-use does not infer a safe destination from a secret name.
Use test credentials only. The app receives values that qc-use types, and can send them elsewhere.

## Allowed sites

qc-use stays on the start site. Add more sites with `allow:`:

```yaml
allow: [auth.localhost:3000, "*.example.test"]
```

- Before a click on a link, qc-use checks the link target. A link to another site stops the step.
- After each action and verification read, qc-use checks the page address. An outside address blocks the step.
- Background requests are not filtered. Script navigation can reach another site before qc-use detects it.
- If the page opens a new tab or window, the step is blocked.

## Production URLs

qc-use refuses to start if the URL looks like production. These URLs are allowed:

- `localhost` and IP addresses on your own network.
- Names that end with `.test`, `.local`, `.localhost`, `.internal`, or `.example`.
- Names with a label such as `staging`, `dev`, `preview`, `qa`, `test`, `sandbox`, or `demo`, excluding the final suffix.

A public `.dev` address is not automatically safe. These name checks are heuristics, not proof that a site is staging.
Some deployment preview names need explicit `allow_production: true`. qc-use does not trust every host on a shared deployment domain.

To run against another URL, set `allow_production: true` in the test file, or use `--allow-production`. Do this only if you are sure.

## Never-do rules

Before each click, fill, dropdown choice, or upload, the gate asks Jev one question per active rule.
The question is: "Can this action break the rule?" Each action receives a new verdict.
Typing and uploads can submit data through page handlers. Scrolling and waiting skip the gate.

The default rules are:

- Never permanently delete an account, workspace, project, or stored data.
- Never make a payment, a purchase, or a subscription change.
- Never send an email, message, or invitation to a real person.

Add your own rules with `never:`. Remove the defaults with `never_defaults: false`.

If the probability is 0.3 or more (`never_threshold`), qc-use does not do the action:

- If you run qc-use in a terminal, it asks you: "Allow it for the rest of this run?"
- If a coding agent runs qc-use, the run stops with outcome `needs approval` and exit code 3. The report shows a command to run again with `--allow "<rule>"`.

The gate also checks `confirm()` dialogs, such as "Delete this workspace?".

**The gate is a seatbelt, not a sandbox.** Jev can make mistakes. Page text can try to trick a model. The real protection is a test account, test data, and the allowed-sites list.

## Dialogs

| Dialog | What qc-use does |
| --- | --- |
| `alert()` | qc-use accepts it and records it in the report. |
| `confirm()` | Jev chooses accept or dismiss. Before qc-use accepts, the gate checks the never-do rules. |
| `prompt()` | The step is blocked. |
| Leave-page warning | qc-use accepts it. |

## Limits

- Each step has an action limit (15 by default) and a decision limit (twice the action limit).
- Each test has an action limit (60 by default).
- Each run has a cost limit (`max_cost`, $0.25 by default). The limit stops the next request after reported spend reaches it.
  One request can exceed the remaining amount. Unknown or invalid pricing stops further requests.
  Direct TypeSafe requests use a Jev token estimate. Other providers must report cost; Jev pricing is not applied to them.
- qc-use never repeats an action to make a step pass. `--repeat N` runs the whole test again in a new profile, and the report shows the pass rate.
- Each run uses a new, empty Chrome profile. qc-use deletes the profile after the run. Use `--profile DIR` to keep a profile.

## Report a security problem

Read [SECURITY.md](../SECURITY.md).
