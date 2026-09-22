# How it works

qc-use has two layers:

- **The engine** (`qc_use/engine/`) reads a page, asks Jev for the next action, and does the action. It is adapted from [jev-ultrafast](https://github.com/browser-use/jev-ultrafast) by Browser Use.
- **The QA layer** (`qc_use/`) reads test files, runs the steps, checks the results, applies the safety rules, and writes reports.

## A run

1. `qc-use run` reads the test file and checks it (`spec.py`).
2. qc-use checks the URL, the secrets, and the key. If something is wrong, it stops with exit code 4.
3. qc-use starts Chrome with a new, empty profile (`chrome.py`).
4. For each step, the engine runs until Jev says that the step is done, or until the step cannot continue (`engine/agent.py`).
5. qc-use checks the step on a fresh read of the page (`runner.py`, `judge.py`).
6. qc-use writes the report (`report.py`) and closes Chrome.

## One decision

Each decision is one request to Jev.

1. **Read the page.** One script in the page (`engine/snapshot.js`) reads the visible text and the controls: links, buttons, fields, dropdowns, checkboxes, and file fields. Each element gets a number.
2. **Ask Jev.** The request has several questions. All of them see the same page:
   - `operation`: which action is next? `CLICK`, `TYPE_TEXT`, `SELECT`, `UPLOAD`, `SCROLL_DOWN`, `SCROLL_UP`, `WAIT`, `DONE`, or `BLOCKED`.
   - `click_target`, `type_text_target`, and the others: if that action is next, which element?
   - `step_done`: is the step's expectation already true?
3. **Use only the matching answer.** If Jev chooses `CLICK`, only `click_target` counts. The other target answers do nothing. This is called speculative fan-out: qc-use asks every question at once, so one round trip is enough.
4. **Check the answer.** Every answer must be a valid choice from the list, with valid probabilities. If not, nothing happens.
5. **Run the gate.** Before a click or a dropdown choice, the gate checks the never-do rules (`guards.py`).
6. **Do the action.** Code finds the element again, checks that it is still visible and not covered, and then clicks or types. For a text field, the text helper writes the value. For a secret, code types the value.
7. **Record, then read again.** qc-use records the action before it reads the page again. A page change during the read cannot hide the action.

Jev never writes a selector, a coordinate, or code. Every action uses an element that qc-use saw on the page.

## Why the text helper is separate

Jev chooses. It does not write text. When a field needs text, such as a name, a small language model (the text helper) writes it. It gets the step, the persona, the field, and the page text. It must answer with a small JSON object. qc-use checks that object before it types anything.

## Stale pages

The page can change between the read and the action. qc-use checks the page again right before each action. If the element or the nearby form changed, qc-use throws the decision away and asks Jev again. qc-use never repeats an action that already happened.

## Dialogs

A browser dialog, such as `confirm()`, freezes the page. qc-use sends each input from a second thread. The main thread watches for dialogs. When a dialog opens, qc-use decides it (see [safety.md](safety.md)), and then the input finishes.

## Checks after a step

When a step is done, qc-use reads the page again. It asks Jev one yes-or-no question for each `expect:` line. Code checks each `check:` line. See [test-files.md](test-files.md#expectations).

Jev's "done" and the checks are separate questions. The checks see a fresh page. This is why a wrong "done" cannot make a step pass.

## What changed from jev-ultrafast

- Test files with ordered steps, expectations, and exact checks.
- Named secrets, password fields, and file uploads.
- The gate, allowed sites, and production URL detection.
- Dialogs, new tab detection, and browser signals.
- A private Chrome for each run, instead of a tab in your everyday Chrome.
- Pydantic models for the test file, Jev answers, and the report.
- Vercel AI Gateway as the default route for Jev and the text helper.
